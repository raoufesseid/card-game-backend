from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import random

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cardgame.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ------------------------------
# MODELS
# ------------------------------

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    score = db.Column(db.Integer, default=0)

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    current_round = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default="waiting")  # waiting, in_progress, finished

class GamePlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    hand = db.Column(db.PickleType)
    played_card = db.Column(db.String(5))

class Move(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    round_number = db.Column(db.Integer)
    card_code = db.Column(db.String(5))

# ------------------------------
# DATABASE INIT
# ------------------------------

with app.app_context():
    db.create_all()

# ------------------------------
# HELPER FUNCTIONS
# ------------------------------

def generate_deck():
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits = ["H", "D", "C", "S"]
    deck = [rank + suit for rank in ranks for suit in suits]
    random.shuffle(deck)
    return deck

def card_value(card):
    rank = card[:-1]
    if rank.isdigit():
        return int(rank)
    return {"J": 11, "Q": 12, "K": 13, "A": 14}[rank]

# ------------------------------
# API ENDPOINTS
# ------------------------------

@app.post("/players")
def create_player():
    data = request.json
    player = Player(name=data["name"])
    db.session.add(player)
    db.session.commit()
    return jsonify({"player_id": player.id, "name": player.name}), 201


@app.post("/games")
def create_game():
    game = Game()
    db.session.add(game)
    db.session.commit()
    return jsonify({"game_id": game.id, "current_round": 1, "status": "waiting"}), 201


@app.post("/games/<int:game_id>/join")
def join_game(game_id):
    data = request.json
    gp = GamePlayer(
        game_id=game_id,
        player_id=data["player_id"],
        hand=[],
        played_card=None
    )
    db.session.add(gp)
    db.session.commit()
    return jsonify({"message": "joined", "game_id": game_id})


@app.get("/games/<int:game_id>/hand/<int:player_id>")
def get_hand(game_id, player_id):
    gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()

    if not gp:
        return jsonify({"error": "player not in this game"}), 400

    # إذا لم يكن لديه يد بعد، وزّع 5 أوراق
    if not gp.hand:
        deck = generate_deck()
        gp.hand = deck[:5]
        db.session.commit()

    return jsonify({
        "game_id": game_id,
        "player_id": player_id,
        "hand": gp.hand
    })


@app.post("/games/<int:game_id>/play")
def play_card(game_id):
    data = request.json
    player_id = data["player_id"]
    card = data["card_code"].strip().upper()

    gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
    if not gp:
        return jsonify({"error": "player not in this game"}), 400

    if not gp.hand:
        return jsonify({"error": "player has no cards"}), 400

    # نأخذ نسخة من اليد حتى SQLAlchemy يحس بالتغيير
    current_hand = list(gp.hand) if isinstance(gp.hand, list) else []

    # تأكد أن الكرت من ضمن اليد فعلاً
    if card not in current_hand:
        return jsonify({"error": "card not in player hand"}), 400

    # احذف الكرت من النسخة ثم أعد تعيينها
    current_hand.remove(card)
    gp.hand = current_hand
    gp.played_card = card
    db.session.commit()

    # سجّل الحركة في جدول Move
    game = Game.query.get(game_id)
    move = Move(
        game_id=game_id,
        player_id=player_id,
        round_number=game.current_round,
        card_code=card
    )
    db.session.add(move)
    db.session.commit()

    # الآن افحص هل اللاعب الآخر لعب أيضاً
    players = GamePlayer.query.filter_by(game_id=game_id).all()
    played = [p for p in players if p.played_card]

    if len(played) < 2:
        return jsonify({"message": "card played, waiting opponent..."})

    # عند هذه النقطة: لاعبان لعبوا
    p1, p2 = played[:2]
    v1 = card_value(p1.played_card)
    v2 = card_value(p2.played_card)

    if v1 > v2:
        winner = p1.player_id
    elif v2 > v1:
        winner = p2.player_id
    else:
        winner = None  # تعادل

    if winner is not None:
        winner_player = Player.query.get(winner)
        if winner_player:
            winner_player.score += 1
            db.session.commit()

    # جهّز الجولة التالية
    game.current_round += 1
    game.status = "in_progress"
    db.session.commit()

    # صفّر played_card للجولة القادمة
    p1.played_card = None
    p2.played_card = None
    db.session.commit()

    return jsonify({
        "winner": winner,
        "round": game.current_round,
        "values": {
            str(p1.player_id): v1,
            str(p2.player_id): v2
        }
    })


@app.get("/games/<int:game_id>")
def game_status(game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"error": "game not found"}), 404

    players = GamePlayer.query.filter_by(game_id=game_id).all()

    result = {
        "game_id": game_id,
        "current_round": game.current_round,
        "status": game.status,
        "players": []
    }

    for p in players:
        pl = Player.query.get(p.player_id)
        if pl:
            result["players"].append({
                "player_id": pl.id,
                "score": pl.score
            })

    return jsonify(result)


@app.get("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    # يسمح لأجهزة أخرى في نفس الشبكة بالدخول
    app.run(host="0.0.0.0", port=5000)
