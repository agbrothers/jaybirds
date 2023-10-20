import json
from lib2to3.pgen2.pgen import generate_grammar
from flask import Flask, session, request, redirect, url_for, jsonify, render_template
from flask_httpauth import HTTPBasicAuth
from flask_socketio import SocketIO, join_room, leave_room, send
from string import ascii_uppercase
from copy import deepcopy
import random
import sys
import os

# to accommodate if run from jaybirds directory
if os.path.isdir('code'):
    os.chdir(os.path.abspath('code'))

from board import ROOMS, CHARACTERS, WEAPONS


## FLASK SETUP
app = Flask(__name__)
auth = HTTPBasicAuth()
socketio = SocketIO(app)
app.secret_key = 'your_secret_key_here'


## VARIABLES
games = {}
users = json.load(open("credentials.json"))

## GENERATE GAME CODES
def generate_unique_code(length):
    while True:
        game = "".join(random.choices(ascii_uppercase, k=length))
        if game not in games: return game

## AUTHENTICATE USERNAME AND PASSWORD
@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

## THROW ERROR FOR INCORRECT USER CREDENTIALS
@auth.error_handler
def unauthorized():
    return jsonify({'error': 'Unauthorized access'}), 401
    

###############
## WEB PAGES ##
###############

## HOME PAGE
@app.route("/", methods=["POST", "GET"])
@auth.login_required
def home():
    session.clear()
    if request.method == "POST":
        ## PULL DATA FROM HTML FORM
        name = request.form.get("name", "")
        code = request.form.get("code", "")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        ## WARN USER IF JOINING/CREATING A GAME WITHOUT ENTERING A NAME
        if name == "":
            return render_template("home.html", error="Please enter a name.", code=code, name=name)
        ## WARN USER IF TRYING TO JOIN A GAME WITHOUT ENTERING A CODE
        if join != False and code == "":
            return render_template("home.html", error="Please enter a code.", code=code, name=name)
        ## GENERATE A NEW GAME 
        if create != False:
            code = generate_unique_code(4)
            games[code] = {
                "num_players": 0, 
                "messages": [], 
                "taken_characters": [], 
                "players": {},
                "available_characters": deepcopy(CHARACTERS), 
                "board": deepcopy(ROOMS),
            } #, "board": Board(...)}
            # print(games[code]["available_characters"])
        ## WARN USER TRYING TO JOIN A NON-EXISTANT GAME
        elif join != False and code not in games:
            return render_template("home.html", error="Game does not exist", code=code, name=name)

        ## ADD USER NAME AND GAME CODE TO THE SESSION DICT (CLIENT SIDE)
        session["game_code"] = code
        session["name"] = name
        return redirect(url_for("character"))
    ## RENDER THE HOME PAGE
    return render_template('home.html')


## CHARACTER SELECTION PAGE
@app.route("/character", methods=["POST", "GET"])
@auth.login_required
def character():
    ## PULL DATA FROM SESSION DICT
    name = session.get("name", "")
    game_code = session.get("game_code", "")

    ## REDIRECT TO THE GAME PAGE WHEN THE USER HITS CONTINUE
    if request.method == "POST":
        cont = request.form.get("continue", False)
        if cont != False:
            return redirect(url_for("game"))

    ## REDIRECT HOME IF USER TRIES JOINING A GAME THAT DOESN'T EXIST
    if game_code is None or session.get("game_code") is None or game_code not in games:
        return redirect(url_for("home"))

    ## RENDER THE SELECTION PAGE
    return render_template("character.html", game=game_code, name=name, characters=games[game_code]["available_characters"], taken_characters=games[game_code]["taken_characters"])


## GAME BOARD PAGE
@app.route("/game")
@auth.login_required
def game():
    ## PULL DATA FROM SESSION DICT
    name = session.get("name")
    game_code = session.get("game_code")
    character = games[game_code]["players"][name]
    
    ## REDIRECT HOME IF USER TRIES JOINING A GAME THAT DOESN'T EXIST
    if game_code is None or session.get("game_code") is None or game_code not in games:
        return redirect(url_for("home"))
    
    ## RENDER THE GAME PAGE
    return render_template("game.html", game=game_code, character=character, messages=games[game_code]["messages"])


#########################
## MESSAGING FUNCTIONS ##
#########################

## CONNECTS TO A GAME ROOM
@socketio.on("connect")
def connect(auth):
    ## PULL DATA FROM SESSION DICT
    game_code = session.get("game_code")
    name = session.get("name")

    ## HANDLE INVALID GAME CODES
    if not game_code or not name: return
    if game_code not in games: 
        leave_room(game_code)
        return

    ## ADD USER TO GAME AND SEND MESSAGE TO PLAYERS
    join_room(game_code)
    send({"name":name, "message": "has entered the game"}, to=game_code)
    ## UPDATE GAME DICT WITH PLAYER INFO
    games[game_code]["num_players"] += 1
    games[game_code]["players"][name] = None
    print(f"{name} joined game {game_code}")

## LEAVES A GAME ROOM
@socketio.on("disconnect")
def disconnect():
    ## PULL DATA FROM SESSION DICT
    game_code = session.get("game_code")
    name = session.get("name")
    leave_room(game_code)

    ## REMOVE GAME IF ALL PLAYERS LEAVE
    if game_code in games and games[game_code]["num_players"] < 1:
        del games[game_code]

    ## SEND MESSAGE TO GAME LOBBY WHEN A USER LEAVES
    send({"name":name, "message": "has left the game"}, to=game_code)
    print(f"{name} left game {game_code}")

## SEND A MESSAGE TO ALL USERS
@socketio.on("message")
def message(data):
    ## PULL GAME CODE FROM SESSION DICT
    game_code = session.get("game_code")
    if game_code not in games: return
    
    ## BUILD MESSAGE FROM ARGUMENTS
    content = {
        "name": session.get("name"),
        "message": data["data"],
    }
    ## SEND MESSAGE TO ALL USERS IN THE GAME LOBBY
    send(content, to=game_code)
    games[game_code]["messages"].append(content)
    print(f"{session.get('name')} said {data['data']}")

## SEND CHARACTER SELECTION TO ALL OTHER USERS
@socketio.on("select_character")
def select_character(data):
    ## PULL DATA FROM SESSION DICT
    name = session.get("name")
    game_code = session.get("game_code")
    if game_code not in games: return

    ## UPDATE GAME DATA WITH SELECTED CHARACTER
    character = [data["character"]][0]
    session["character"] = character
    games[game_code]["players"][name] = character
    ## REMOVE CHARACTER FROM AVAILABLE SET
    del games[game_code]["available_characters"][character]
    games[game_code]["taken_characters"].append(character)
    ## BUILD CHARACTER SELECTION MESSAGE
    content = {
        "name": session.get("name"),
        "character": character,
        "message": f"has chosen {character}"
    }
    ## SEND CHARACTER SELECTION MESSAGE TO PLAYERS
    send(content, to=game_code)
    # print(f"\n{session.get('name')} selected {character}")
    # print(games[game_code]["players"])
    # print(f"Characters Available: {games[game_code]['available_characters']}\n")

    return redirect(url_for("game"))
    # return redirect(url_for("view_board"))


@socketio.on("view_board")
def view_board(data):
    return render_template("board.html", board=games[game_code]['board'])


if __name__ == '__main__':

    socketio.run(app)
    # socketio.run(app, debug=True)
    # app.run()





# ## export FLASK_APP=clue
# ## export FLASK_ENV=development
# ## flask run --host=0.0.0.0 -p 5001
# ngrok http <port>
