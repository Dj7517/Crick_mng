# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

# ─────────────────────────────────────────
# Tournament
# ─────────────────────────────────────────
class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    teams = db.relationship("Team", backref="tournament", cascade="all,delete-orphan")
    matches = db.relationship("Match", backref="tournament", cascade="all,delete-orphan")
    settings = db.Column(db.Text, default="{}")

    def settings_dict(self):
        try:
            return json.loads(self.settings or "{}")
        except:
            return {}

# ─────────────────────────────────────────
# Team
# ─────────────────────────────────────────
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournament.id"), nullable=False)
    players = db.relationship("Player", backref="team", cascade="all,delete-orphan")
    logo = db.Column(db.String(300), nullable=True)
    playing_xi = db.Column(db.Text, default="[]")  # json list

# ─────────────────────────────────────────
# Player
# ─────────────────────────────────────────
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    # Batting
    runs = db.Column(db.Integer, default=0)
    balls_faced = db.Column(db.Integer, default=0)

    # Bowling
    wickets = db.Column(db.Integer, default=0)
    balls_bowled = db.Column(db.Integer, default=0)
    runs_conceded = db.Column(db.Integer, default=0)

    is_keeper = db.Column(db.Boolean, default=False)
    is_captain = db.Column(db.Boolean, default=False)

# ─────────────────────────────────────────
# Match
# ─────────────────────────────────────────
class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournament.id"), nullable=False)
    teamA_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    teamB_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    scheduled = db.Column(db.String(140), nullable=True)
    played = db.Column(db.Boolean, default=False)
    toss_winner_id = db.Column(db.Integer, nullable=True)
    toss_choice = db.Column(db.String(20), nullable=True)

    a_runs = db.Column(db.Integer, default=0)
    a_overs = db.Column(db.String(20), default="0.0")
    a_wickets = db.Column(db.Integer, default=0)

    b_runs = db.Column(db.Integer, default=0)
    b_overs = db.Column(db.String(20), default="0.0")
    b_wickets = db.Column(db.Integer, default=0)

    winner = db.Column(db.String(20), nullable=True)
    ball_by_ball = db.Column(db.Text, default="[]")

    deliveries = db.relationship("Delivery", backref="match", lazy=True, cascade="all, delete-orphan")

# ─────────────────────────────────────────
# Delivery (BALL-BY-BALL)
# ─────────────────────────────────────────
class Delivery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)

    over = db.Column(db.Integer, nullable=False)
    ball_in_over = db.Column(db.Integer, nullable=False)

    batting_team_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    bowling_team_id = db.Column(db.Integer, db.ForeignKey("team.id"))

    striker_id = db.Column(db.Integer, db.ForeignKey("player.id"))
    non_striker_id = db.Column(db.Integer)
    bowler_id = db.Column(db.Integer, db.ForeignKey("player.id"))

    runs = db.Column(db.Integer, default=0)
    extras = db.Column(db.String(20), default="")
    wicket = db.Column(db.Boolean, default=False)
    wicket_type = db.Column(db.String(50), default="")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────
# Utility functions for leaderboard
# ─────────────────────────────────────────
def top_batsmen_for_team(team_id):
    result = db.session.query(
        Player.name,
        db.func.sum(Delivery.runs).label("total_runs")
    ).join(Delivery, Player.id == Delivery.striker_id) \
     .filter(Player.team_id == team_id) \
     .group_by(Player.id) \
     .order_by(db.desc("total_runs")) \
     .limit(5).all()
    return result


def top_bowlers_for_team(team_id):
    result = db.session.query(
        Player.name,
        db.func.count(Delivery.id).label("total_wickets")
    ).join(Delivery, Player.id == Delivery.bowler_id) \
     .filter(Player.team_id == team_id, Delivery.wicket == True) \
     .group_by(Player.id) \
     .order_by(db.desc("total_wickets")) \
     .limit(5).all()
    return result
