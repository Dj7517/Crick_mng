import json
from random import shuffle
from itertools import combinations
from math import floor

def overs_to_balls(overs):
    if not overs:
        return 0
    s = str(overs)
    if '.' in s:
        a, b = s.split('.')
        try:
            return int(a) * 6 + int(b)
        except:
            return 0
    try:
        return int(float(s)) * 6
    except:
        return 0


def balls_to_overs(balls):
    o = balls // 6
    b = balls % 6
    return f"{o}.{b}"


def compute_points_and_nrr(matches, teams):
    stats = {
        t.id: {
            "played": 0, "won": 0, "lost": 0, "tied": 0, "points": 0,
            "runs_for": 0, "balls_faced": 0, "runs_against": 0, "balls_bowled": 0
        } for t in teams
    }

    for m in matches:
        if not m.played:
            continue

        A = m.teamA_id
        B = m.teamB_id
        a_runs = int(m.a_runs or 0)
        b_runs = int(m.b_runs or 0)
        a_balls = overs_to_balls(m.a_overs)
        b_balls = overs_to_balls(m.b_overs)

        stats[A]["played"] += 1
        stats[B]["played"] += 1

        stats[A]["runs_for"] += a_runs
        stats[A]["balls_faced"] += a_balls
        stats[A]["runs_against"] += b_runs
        stats[A]["balls_bowled"] += b_balls

        stats[B]["runs_for"] += b_runs
        stats[B]["balls_faced"] += b_balls
        stats[B]["runs_against"] += a_runs
        stats[B]["balls_bowled"] += a_balls

        if a_runs > b_runs:
            stats[A]["won"] += 1; stats[B]["lost"] += 1; stats[A]["points"] += 2
        elif b_runs > a_runs:
            stats[B]["won"] += 1; stats[A]["lost"] += 1; stats[B]["points"] += 2
        else:
            stats[A]["tied"] += 1; stats[B]["tied"] += 1
            stats[A]["points"] += 1; stats[B]["points"] += 1

    rows = []
    for t in teams:
        st = stats[t.id]
        rf, bf = st["runs_for"], st["balls_faced"]
        ra, bb = st["runs_against"], st["balls_bowled"]
        rpo = (rf / (bf / 6)) if bf > 0 else 0
        rpo_against = (ra / (bb / 6)) if bb > 0 else 0
        nrr = round(rpo - rpo_against, 3)

        rows.append({
            "team_id": t.id,
            "team_name": t.name,
            "played": st["played"],
            "won": st["won"],
            "lost": st["lost"],
            "tied": st["tied"],
            "points": st["points"],
            "nrr": nrr
        })

    return sorted(rows, key=lambda row: (row["points"], row["nrr"]), reverse=True)


def simple_scheduler(team_ids, matches_per_team=3):
    s = []
    counts = {t: 0 for t in team_ids}
    pool = team_ids[:]

    for _ in range(500):
        shuffle(pool)
        for i in range(len(pool) - 1):
            a, b = pool[i], pool[i+1]
            if a == b:
                continue
            if counts[a] < matches_per_team and counts[b] < matches_per_team:
                key = tuple(sorted((a, b)))
                if key not in {tuple(sorted(p)) for p in s}:
                    s.append((a, b))
                    counts[a] += 1
                    counts[b] += 1

    return s


# ---- Import models now (to avoid circular import earlier) ----
from models import Player, Delivery


def top_batsmen_for_team(team_id, limit=5):
    return Player.query.filter_by(team_id=team_id).order_by(Player.runs.desc()).limit(limit).all()


def top_bowlers_for_team(team_id, limit=5):
    players = Player.query.filter_by(team_id=team_id).all()
    players_sorted = sorted(players, key=lambda p: (-p.wickets, p.bowling_economy()))
    return players_sorted[:limit]


def match_score_summary(match_id):
    totals = {}
    deliveries = Delivery.query.filter_by(match_id=match_id).order_by(Delivery.created_at.asc()).all()

    for d in deliveries:
        t = d.batting_team_id
        totals.setdefault(t, {"runs": 0, "wickets": 0, "balls": 0})
        totals[t]["runs"] += d.runs
        if d.wicket:
            totals[t]["wickets"] += 1
        if d.extras not in ["WD", "NB"]:
            totals[t]["balls"] += 1

    for t, v in totals.items():
        balls = v["balls"]
        v["overs"] = f"{balls // 6}.{balls % 6}"

    return {"totals": totals, "deliveries": deliveries}
