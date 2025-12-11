from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Player(db.Model):
    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)


class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="waiting")  # waiting, in_progress, finished
    current_round = db.Column(db.Integer, default=1)
    winner_player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)


class GamePlayer(db.Model):
    __tablename__ = "game_players"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    score = db.Column(db.Integer, default=0)


class CardInHand(db.Model):
    __tablename__ = "cards_in_hand"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    card_code = db.Column(db.String(5), nullable=False)  # مثال: "AH", "10S"
    is_played = db.Column(db.Boolean, default=False)


class Move(db.Model):
    __tablename__ = "moves"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    card_code = db.Column(db.String(5), nullable=False)
