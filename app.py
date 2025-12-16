# =========================
#  app.py  (FULL VERSION)
#  Flask + SQLAlchemy + SocketIO (WebSocket)
#  Turn-based 2-player card game
# =========================

import os
import random

# ✅ IMPORTANT: must be BEFORE flask imports for websockets
import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit

# -------------------------
# App setup
# -------------------------
app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "cardgame.db")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ✅ WebSocket
socketio = SocketIO(app, cors_allowed_origins="*")


# -------------------------
# Models
# -------------------------
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    score = db.Column(db.Integer, default=0)


class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(30), default="waiting")  # waiting / in_progress / finished
    current_round = db.Column(db.Integer, default=1)
    winner_id = db.Column(db.Integer, nullable=True)


class GamePlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)

    # store hand as comma-separated values "QH,7S,10C"
    hand = db.Column(db.Text, default="")
    played_card = db.Column(db.String(10), nullable=True)


class Move(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, nullable=False)
    player_id = db.Column(db.Integer, nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    card_code = db.Column(db.String(10), nullable=False)


# -------------------------
# Helpers
# -------------------------
def create_deck():
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["H", "D", "C", "S"]  # Hearts, Diamonds, Clubs, Spades
    return [r + s for s in suits for r in ranks]


def card_value(card_code: str) -> int:
    # "QH" -> 12, "10C" -> 10, "AS" -> 14
    rank = card_code[:-1]  # everything except last char suit
    mapping = {"J": 11, "Q": 12, "K": 13, "A": 14}
    if rank in mapping:
        return mapping[rank]
    return int(rank)


def hand_to_list(hand_text: str):
    if not hand_text:
        return []
    return [x.strip() for x in hand_text.split(",") if x.strip()]


def list_to_hand(cards):
    return ",".join(cards)


def game_room(game_id: int) -> str:
    return f"game_{game_id}"


def emit_game_state(game_id: int):
    """Send a quick update via websocket to everyone in this game room."""
    g = Game.query.get(game_id)
    if not g:
        return

    gps = GamePlayer.query.filter_by(game_id=game_id).all()
    players_payload = []
    for gp in gps:
        p = Player.query.get(gp.player_id)
        players_payload.append({
            "player_id": gp.player_id,
            "name": p.name if p else "",
            "score": p.score if p else 0
        })

    socketio.emit(
        "game_update",
        {
            "type": "state",
            "game_id": g.id,
            "status": g.status,
            "current_round": g.current_round,
            "winner_id": g.winner_id,
            "players": players_payload
        },
        room=game_room(game_id)
    )


# -------------------------
# Create DB (first run)
# -------------------------
with app.app_context():
    db.create_all()


# -------------------------
# Routes (Frontend)
# -------------------------
@app.get("/")
def home():
    # if you have templates/index.html it will open your UI
    # otherwise it will error. So keep it if you want.
    return render_template("index.html")


# -------------------------
# API: Players
# -------------------------
@app.post("/players")
def create_player():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "Player").strip()

    p = Player(name=name, score=0)
    db.session.add(p)
    db.session.commit()

    return jsonify({"player_id": p.id, "name": p.name}), 201


@app.get("/players")
def list_players():
    players = Player.query.all()
    return jsonify([{"player_id": p.id, "name": p.name, "score": p.score} for p in players])


# -------------------------
# API: Games
# -------------------------
@app.post("/games")
def create_game():
    g = Game(status="waiting", current_round=1, winner_id=None)
    db.session.add(g)
    db.session.commit()

    return jsonify({
        "game_id": g.id,
        "status": g.status,
        "current_round": g.current_round
    }), 201


@app.get("/games/<int:game_id>")
def get_game(game_id):
    g = Game.query.get(game_id)
    if not g:
        return jsonify({"error": "game not found"}), 404

    gps = GamePlayer.query.filter_by(game_id=game_id).all()
    players = []
    for gp in gps:
        p = Player.query.get(gp.player_id)
        players.append({
            "player_id": gp.player_id,
            "score": p.score if p else 0
        })

    return jsonify({
        "game_id": g.id,
        "status": g.status,
        "current_round": g.current_round,
        "winner_id": g.winner_id,
        "players": players
    })


@app.post("/games/<int:game_id>/join")
def join_game(game_id):
    data = request.get_json(force=True) or {}
    player_id = int(data.get("player_id", 0))

    g = Game.query.get(game_id)
    if not g:
        return jsonify({"error": "game not found"}), 404

    p = Player.query.get(player_id)
    if not p:
        return jsonify({"error": "player not found"}), 404

    existing = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
    if existing:
        return jsonify({"game_id": game_id, "message": "already joined"}), 200

    # only allow 2 players
    count = GamePlayer.query.filter_by(game_id=game_id).count()
    if count >= 2:
        return jsonify({"error": "game is full (2 players max)"}), 400

    # deal 5 cards from a shuffled deck (simple demo)
    deck = create_deck()
    random.shuffle(deck)
    hand_cards = deck[:5]

    gp = GamePlayer(
        game_id=game_id,
        player_id=player_id,
        hand=list_to_hand(hand_cards),
        played_card=None
    )
    db.session.add(gp)

    # if this is second player -> start game
    if count == 1:
        g.status = "in_progress"

    db.session.commit()

    # WebSocket notify room (if players are connected)
    socketio.emit(
        "system",
        {"message": f"Player {player_id} joined game {game_id}"},
        room=game_room(game_id)
    )
    emit_game_state(game_id)

    return jsonify({"game_id": game_id, "message": "joined"}), 200


@app.get("/games/<int:game_id>/hand/<int:player_id>")
def get_hand(game_id, player_id):
    gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
    if not gp:
        return jsonify({"error": "player not in this game"}), 400

    return jsonify({
        "game_id": game_id,
        "player_id": player_id,
        "hand": hand_to_list(gp.hand)
    })


# -------------------------
# API: Play card (IMPORTANT)
# -------------------------
@app.post("/games/<int:game_id>/play")
def play_card(game_id):
    data = request.get_json(force=True) or {}
    player_id = int(data.get("player_id", 0))
    card = (data.get("card_code") or "").strip().upper()

    g = Game.query.get(game_id)
    if not g:
        return jsonify({"error": "game not found"}), 404

    gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
    if not gp:
        return jsonify({"error": "player not in this game"}), 400

    if g.status not in ("in_progress", "waiting"):
        return jsonify({"error": "game is not active"}), 400

    # ✅ Prevent playing twice in same round
    if gp.played_card:
        return jsonify({"error": "you already played this round"}), 400

    # ✅ Check card exists in hand
    hand_cards = hand_to_list(gp.hand)
    if card not in hand_cards:
        return jsonify({"error": "card not in player hand"}), 400

    # ✅ Remove card from hand so it cannot be played again
    hand_cards.remove(card)
    gp.hand = list_to_hand(hand_cards)

    # mark played
    gp.played_card = card
    db.session.commit()

    # log move
    move = Move(
        game_id=game_id,
        player_id=player_id,
        round_number=g.current_round,
        card_code=card
    )
    db.session.add(move)
    db.session.commit()

    # WebSocket: tell room someone played
    socketio.emit(
        "game_update",
        {
            "type": "card_played",
            "game_id": game_id,
            "player_id": player_id,
            "card_code": card,
            "round": g.current_round
        },
        room=game_room(game_id)
    )

    # check if both played
    players = GamePlayer.query.filter_by(game_id=game_id).all()
    played = [x for x in players if x.played_card]

    if len(played) < 2:
        return jsonify({"message": "card played, waiting opponent..."}), 200

    # round resolution
    p1, p2 = played[0], played[1]
    v1 = card_value(p1.played_card)
    v2 = card_value(p2.played_card)

    if v1 > v2:
        winner = p1.player_id
    elif v2 > v1:
        winner = p2.player_id
    else:
        winner = None

    if winner is not None:
        wp = Player.query.get(winner)
        if wp:
            wp.score += 1
            db.session.commit()

    # prepare next round
    g.current_round += 1
    g.status = "in_progress"
    db.session.commit()

    # clear played cards for next round
    p1.played_card = None
    p2.played_card = None
    db.session.commit()

    # WebSocket: send round result
    socketio.emit(
        "game_update",
        {
            "type": "round_result",
            "game_id": game_id,
            "winner": winner,
            "values": {str(p1.player_id): v1, str(p2.player_id): v2},
            "round": g.current_round
        },
        room=game_room(game_id)
    )
    emit_game_state(game_id)

    return jsonify({
        "winner": winner,
        "round": g.current_round,
        "values": {str(p1.player_id): v1, str(p2.player_id): v2}
    }), 200


# -------------------------
# WebSocket Events
# -------------------------
@socketio.on("join_game")
def ws_join_game(data):
    game_id = int(data.get("game_id", 0))
    player_id = data.get("player_id", "unknown")

    if not game_id:
        emit("system", {"message": "Missing game_id"})
        return

    room = game_room(game_id)
    join_room(room)

    emit("system", {"message": f"Connected to room {room} (Player {player_id})"})
    emit_game_state(game_id)


@socketio.on("leave_game")
def ws_leave_game(data):
    game_id = int(data.get("game_id", 0))
    if not game_id:
        return
    leave_room(game_room(game_id))


# -------------------------
# Local run (Render uses gunicorn from Procfile)
# -------------------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
