# app.py
import os
import json
import io
import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory, send_file, jsonify
)
from models import db, Tournament, Team, Player, Match, Delivery
from utils import (
    simple_scheduler, compute_points_and_nrr,
    overs_to_balls, balls_to_overs,
    top_batsmen_for_team, top_bowlers_for_team, match_score_summary
)
import pandas as pd

# ----------------------
# Config & paths
# ----------------------


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_FILES = os.path.join(BASE_DIR, "static", "files")
if not os.path.exists(STATIC_FILES):
    os.makedirs(STATIC_FILES)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-key'

# initialize DB
db.init_app(app)
with app.app_context():
    db.create_all()

# ----------------------
# Helper - serve uploaded/static files
# ----------------------
@app.route('/files/<path:filename>')
def files(filename):
    return send_from_directory(STATIC_FILES, filename)

@app.route("/team/<int:team_id>/stats")
def team_stats(team_id):
    team = Team.query.get_or_404(team_id)
    players = Player.query.filter_by(team_id=team_id).all()
    matches = Match.query.filter(
        (Match.teamA_id == team_id) | (Match.teamB_id == team_id)
    ).all()

    return render_template("team_stats.html", team=team, players=players, matches=matches)

   

# ----------------------
# Home / index
# ----------------------
@app.route('/')
def index():
    tours = Tournament.query.order_by(Tournament.created_at.desc()).all()
    return render_template('index.html', tournaments=tours)

@app.route('/tournament/create', methods=['POST'])
def create_tournament():
    name = request.form.get('name') or f"Tournament {datetime.datetime.utcnow().isoformat()}"
    t = Tournament(name=name)
    db.session.add(t); db.session.commit()
    flash("Tournament created", "success")
    return redirect(url_for('tournament_home', tid=t.id))

# ----------------------
# Tournament home (teams + matches)
# ----------------------
@app.route('/tournament/<int:tid>')
def tournament_home(tid):
    tour = Tournament.query.get_or_404(tid)
    teams = Team.query.filter_by(tournament_id=tid).all()
    matches = Match.query.filter_by(tournament_id=tid).all()
    # also compute points table for display (safe)
    try:
        table = compute_points_and_nrr(matches, teams)
    except Exception:
        table = []
    return render_template('tournament.html', tour=tour, teams=teams, matches=matches, table=table)

# ----------------------
# Manage teams & players
# ----------------------
@app.route('/tournament/<int:tid>/teams', methods=['GET','POST'])
def manage_teams(tid):
    tour = Tournament.query.get_or_404(tid)
    if request.method == 'POST':
        name = request.form.get('team_name')
        players_raw = request.form.get('players','')
        players = [p.strip() for p in players_raw.split(',') if p.strip()]
        if not name:
            flash('Team name required', 'danger')
        else:
            team = Team(name=name, tournament_id=tid)
            file = request.files.get('logo')
            if file and file.filename:
                safe_name = f"{int(datetime.datetime.utcnow().timestamp())}_{file.filename}"
                dest = os.path.join(STATIC_FILES, safe_name)
                file.save(dest)
                team.logo = safe_name
            db.session.add(team); db.session.commit()
            for p in players:
                pl = Player(name=p, team_id=team.id)
                db.session.add(pl)
            db.session.commit()
            flash('Team created', 'success')
        return redirect(url_for('manage_teams', tid=tid))

    teams = Team.query.filter_by(tournament_id=tid).all()
    return render_template('teams.html', tour=tour, teams=teams)

@app.route('/team/<int:team_id>/delete', methods=['POST'])
def delete_team(team_id):
    team = Team.query.get_or_404(team_id)
    tid = team.tournament_id
    db.session.delete(team); db.session.commit()
    flash('Team deleted', 'success')
    return redirect(url_for('manage_teams', tid=tid))

@app.route('/team/<int:team_id>/add_player', methods=['POST'])
def add_player(team_id):
    name = request.form.get('player_name')
    if not name:
        flash('Player name required', 'danger')
    else:
        p = Player(name=name, team_id=team_id)
        db.session.add(p); db.session.commit()
        flash('Player added', 'success')
    team = Team.query.get_or_404(team_id)
    return redirect(url_for('manage_teams', tid=team.tournament_id))

# ----------------------
# Scheduler
# ----------------------
@app.route('/tournament/<int:tid>/schedule', methods=['POST'])
def schedule_matches(tid):
    tour = Tournament.query.get_or_404(tid)
    teams = Team.query.filter_by(tournament_id=tid).all()
    team_ids = [t.id for t in teams]
    if len(team_ids) < 2:
        flash('Need at least 2 teams', 'danger')
        return redirect(url_for('tournament_home', tid=tid))

    pairs = simple_scheduler(team_ids, matches_per_team=3)
    created = 0
    for a,b in pairs:
        m = Match(tournament_id=tid, teamA_id=a, teamB_id=b)
        db.session.add(m); created += 1
    db.session.commit()
    flash(f"Scheduled {created} matches", "success")
    return redirect(url_for('tournament_home', tid=tid))

# ----------------------
# Matches list & simple recording
# ----------------------
@app.route('/tournament/<int:tid>/matches')
def matches(tid):
    tour = Tournament.query.get_or_404(tid)
    matches = Match.query.filter_by(tournament_id=tid).all()
    teams_map = {t.id: t.name for t in Team.query.filter_by(tournament_id=tid).all()}
    return render_template('matches.html', tour=tour, matches=matches, teams_map=teams_map)

# Match details (keeps both naming styles for compatibility)
@app.route('/match/<int:mid>/details')
def match_details(mid):
    m = Match.query.get_or_404(mid)
    teamA = Team.query.get(m.teamA_id) if m.teamA_id else None
    teamB = Team.query.get(m.teamB_id) if m.teamB_id else None
    playersA = Player.query.filter_by(team_id=teamA.id).all() if teamA else []
    playersB = Player.query.filter_by(team_id=teamB.id).all() if teamB else []
    # pass variables with both conventions (some templates use m/teamA/teamB; others use match/team1/team2)
    return render_template('match_details.html',
                           m=m, match=m,
                           teamA=teamA, teamB=teamB,
                           team1=teamA, team2=teamB,
                           playersA=playersA, playersB=playersB,
                           team1_players=playersA, team2_players=playersB)

# Record quick match result (form)
@app.route('/match/<int:mid>/record', methods=['POST'])
def record_match(mid):
    m = Match.query.get_or_404(mid)
    # parse safely
    def safe_int(val, default=0):
        try:
            return int(val)
        except Exception:
            return default

    m.a_runs = safe_int(request.form.get('a_runs', 0))
    m.a_overs = request.form.get('a_overs', '0.0') or '0.0'
    m.a_wickets = safe_int(request.form.get('a_wickets', 0))
    m.b_runs = safe_int(request.form.get('b_runs', 0))
    m.b_overs = request.form.get('b_overs', '0.0') or '0.0'
    m.b_wickets = safe_int(request.form.get('b_wickets', 0))

    m.played = True
    if m.a_runs > m.b_runs:
        m.winner = 'A'
    elif m.b_runs > m.a_runs:
        m.winner = 'B'
    else:
        m.winner = 'tie'

    # Update player stats from form inputs (if provided)
    for pl in Player.query.join(Team).filter(Team.tournament_id == m.tournament_id).all():
        r_key = f"p_{pl.id}_runs"
        b_key = f"p_{pl.id}_balls"
        w_key = f"p_{pl.id}_wickets"
        rc_key = f"p_{pl.id}_runs_conceded"
        ob_key = f"p_{pl.id}_overs_bowled"

        if r_key in request.form:
            pl.runs = (pl.runs or 0) + safe_int(request.form.get(r_key, 0))
        if b_key in request.form:
            # your code uses 'balls' for batting balls; models may use 'balls_faced' — ensure consistency
            # we'll update both if they exist
            val = safe_int(request.form.get(b_key, 0))
            if hasattr(pl, 'balls'):
                pl.balls = (pl.balls or 0) + val
            if hasattr(pl, 'balls_faced'):
                pl.balls_faced = (pl.balls_faced or 0) + val
        if w_key in request.form:
            pl.wickets = (pl.wickets or 0) + safe_int(request.form.get(w_key, 0))
        if rc_key in request.form:
            pl.runs_conceded = (pl.runs_conceded or 0) + safe_int(request.form.get(rc_key, 0))
        if ob_key in request.form:
            # convert overs string like "3.4" into balls and add
            try:
                inc = overs_to_balls(request.form.get(ob_key, "0"))
                pl.balls_bowled = (pl.balls_bowled or 0) + inc
            except Exception:
                pass

    db.session.commit()
    flash('Result recorded', 'success')
    return redirect(url_for('matches', tid=m.tournament_id))

# ----------------------
# Ball-by-ball API (append JSON to match.ball_by_ball and update players)
# ----------------------
@app.route('/match/<int:mid>/b2b/add', methods=['POST'])
def add_ball(mid):
    m = Match.query.get_or_404(mid)
    payload = request.get_json() or {}

    # ensure ball_by_ball stored as list
    try:
        bbb = json.loads(m.ball_by_ball or "[]")
        if not isinstance(bbb, list):
            bbb = []
    except Exception:
        bbb = []

    # normalize payload keys (optional)
    # expected fields: over, ball_in_over, batting_team_id, bowling_team_id, batsman_id/striker_id, bowler_id, runs, extras, wicket, is_no_ball, extras_type
    bbb.append(payload)
    m.ball_by_ball = json.dumps(bbb)

    # defensive parsing
    batsman_id = payload.get("batsman_id") or payload.get("striker_id")
    bowler_id = payload.get("bowler_id")
    runs = 0
    try:
        runs = int(payload.get("runs", 0) or 0)
    except Exception:
        runs = 0

    # extras may be string type (like 'WD') or numeric extra-run count; keep both
    extras = payload.get("extras", "")
    extras_runs = 0
    if isinstance(extras, (int, float)):
        extras_runs = int(extras)
    else:
        # if extras value is numeric string, parse
        if isinstance(extras, str) and extras.isdigit():
            extras_runs = int(extras)

    wicket = bool(payload.get("wicket", False))
    is_no_ball = bool(payload.get("is_no_ball", False))
    extras_type = payload.get("extras_type") or payload.get("extras_kind") or ""

    # apply to batsman
    if batsman_id:
        batsman = Player.query.get(batsman_id)
        if batsman:
            batsman.runs = (batsman.runs or 0) + runs
            # only increment batting ball for legal deliveries (not no-ball)
            if not is_no_ball and extras_type not in ['WD']:
                # some code uses 'balls' others use 'balls_faced' — update both if present
                if hasattr(batsman, 'balls'):
                    batsman.balls = (batsman.balls or 0) + 1
                if hasattr(batsman, 'balls_faced'):
                    batsman.balls_faced = (batsman.balls_faced or 0) + 1

    # apply to bowler
    if bowler_id:
        bowler = Player.query.get(bowler_id)
        if bowler:
            # count runs conceded (runs + extras_runs)
            bowler.runs_conceded = (bowler.runs_conceded or 0) + runs + extras_runs
            # increment legal ball only if not wide or no-ball
            if extras_type not in ['WD', 'NB'] and not is_no_ball:
                bowler.balls_bowled = (bowler.balls_bowled or 0) + 1
            if wicket:
                bowler.wickets = (bowler.wickets or 0) + 1

    db.session.commit()
    return jsonify({"status": "ok", "ball_count": len(bbb)})

# ----------------------
# Scoreboard & leaderboards
# ----------------------
@app.route('/tournament/<int:tid>/scoreboard')
def scoreboard(tid):
    tour = Tournament.query.get_or_404(tid)
    teams = Team.query.filter_by(tournament_id=tid).all()
    matches = Match.query.filter_by(tournament_id=tid).all()
    table = compute_points_and_nrr(matches, teams)
    players = Player.query.join(Team).filter(Team.tournament_id == tid).order_by(Player.runs.desc()).limit(20).all()
    orange = players[0] if players else None
    bowlers = Player.query.join(Team).filter(Team.tournament_id == tid).order_by(Player.wickets.desc()).limit(20).all()
    purple = bowlers[0] if bowlers else None
    return render_template('scoreboard.html', tour=tour, table=table, players=players, orange=orange, purple=purple)

# ----------------------
# Export: Excel
# ----------------------
@app.route('/tournament/<int:tid>/export/excel')
def export_excel(tid):
    tour = Tournament.query.get_or_404(tid)
    teams_q = Team.query.filter_by(tournament_id=tid).all()
    matches_q = Match.query.filter_by(tournament_id=tid).all()
    players_q = Player.query.join(Team).filter(Team.tournament_id == tid).all()

    teams = [{"Name": t.name, "Players": ", ".join([p.name for p in t.players])} for t in teams_q]

    matches = []
    for m in matches_q:
        matches.append({
            "MatchID": m.id,
            "TeamA": Team.query.get(m.teamA_id).name if m.teamA_id else "",
            "TeamB": Team.query.get(m.teamB_id).name if m.teamB_id else "",
            "A_runs": m.a_runs, "A_overs": m.a_overs, "A_wkts": m.a_wickets,
            "B_runs": m.b_runs, "B_overs": m.b_overs, "B_wkts": m.b_wickets,
            "Played": m.played, "Winner": m.winner
        })

    players = []
    for p in players_q:
        econ = 0
        if (p.balls_bowled or 0) > 0:
            overs = (p.balls_bowled or 0) / 6.0
            econ = round((p.runs_conceded or 0) / overs, 2) if overs > 0 else 0
        players.append({
            "Name": p.name,
            "Team": p.team.name if p.team else "",
            "Runs": p.runs or 0,
            "Balls": getattr(p, 'balls', getattr(p, 'balls_faced', 0)) or 0,
            "Wickets": p.wickets or 0,
            "Economy": econ
        })

    df1 = pd.DataFrame(teams)
    df2 = pd.DataFrame(matches)
    df3 = pd.DataFrame(players)
    out_path = os.path.join(STATIC_FILES, f"tournament_{tid}_export.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df1.to_excel(writer, sheet_name="Teams", index=False)
        df2.to_excel(writer, sheet_name="Matches", index=False)
        df3.to_excel(writer, sheet_name="Players", index=False)

    return send_from_directory(STATIC_FILES, os.path.basename(out_path), as_attachment=True)

# ----------------------
# Export: PDF
# ----------------------
@app.route('/tournament/<int:tid>/export/pdf')
def export_pdf(tid):
    try:
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception:
        flash("reportlab not installed", "danger")
        return redirect(url_for('scoreboard', tid=tid))

    tour = Tournament.query.get_or_404(tid)
    teams_q = Team.query.filter_by(tournament_id=tid).all()
    matches_q = Match.query.filter_by(tournament_id=tid).all()
    players_q = Player.query.join(Team).filter(Team.tournament_id == tid).all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"Tournament: {tour.name}", styles['Title']))
    story.append(Spacer(1, 12))

    # Points table
    teams = Team.query.filter_by(tournament_id=tid).all()
    table_data = [["Team","P","W","L","T","Pts","RF","RA","NRR"]]
    table_rows = compute_points_and_nrr(matches_q, teams)
    for r in table_rows:
        table_data.append([r['team_name'], r['played'], r['won'], r['lost'], r['tied'], r['points'], r['runs_for'], r['runs_against'], r['nrr']])
    t = Table(table_data)
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey), ('BACKGROUND',(0,0),(-1,0),colors.lightgrey)]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Top players
    story.append(Paragraph("Top Players", styles['Heading2']))
    pdata = [["Player","Team","Runs","Wickets"]]
    for p in players_q[:20]:
        pdata.append([p.name, p.team.name if p.team else '', p.runs or 0, p.wickets or 0])
    tp = Table(pdata)
    tp.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.3,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey)]))
    story.append(tp)

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, download_name=f"tournament_{tid}.pdf", as_attachment=True, mimetype='application/pdf')

# -------------------------
# Live scoring UI + APIs
# -------------------------

@app.route('/live/<int:match_id>')
def live_score_page(match_id):
    m = Match.query.get_or_404(match_id)
    # try to toggle live flag
    try:
        m.is_live = True
        db.session.commit()
    except Exception:
        db.session.rollback()

    teamA = Team.query.get(m.teamA_id) if m.teamA_id else None
    teamB = Team.query.get(m.teamB_id) if m.teamB_id else None
    team1_players = Player.query.filter_by(team_id=m.teamA_id).all() if m.teamA_id else []
    team2_players = Player.query.filter_by(team_id=m.teamB_id).all() if m.teamB_id else []

    return render_template('live_score.html',
                           match=m, m=m,
                           teamA=teamA, teamB=teamB,
                           team1=teamA, team2=teamB,
                           team1_players=team1_players, team2_players=team2_players,
                           playersA=team1_players, playersB=team2_players)

@app.route('/api/match/<int:match_id>/delivery', methods=['POST'])
def post_delivery(match_id):
    data = request.json or {}
    match = Match.query.get_or_404(match_id)
    # create Delivery object
    try:
        d = Delivery(
            match_id = match_id,
            over = int(data.get('over', 0)),
            ball_in_over = int(data.get('ball_in_over', 1)),
            batting_team_id = int(data.get('batting_team_id')) if data.get('batting_team_id') else None,
            bowling_team_id = int(data.get('bowling_team_id')) if data.get('bowling_team_id') else None,
            striker_id = int(data.get('striker_id')) if data.get('striker_id') else None,
            non_striker_id = int(data.get('non_striker_id')) if data.get('non_striker_id') else None,
            bowler_id = int(data.get('bowler_id')) if data.get('bowler_id') else None,
            runs = int(data.get('runs', 0)),
            extras = data.get('extras', ''),
            wicket = bool(data.get('wicket', False)),
            wicket_type = data.get('wicket_type', '')
        )
    except Exception as e:
        return jsonify({'status':'error', 'message': f'invalid payload: {e}'}), 400

    db.session.add(d)

    # update player stats (simple policy)
    if d.striker_id:
        striker = Player.query.get(d.striker_id)
        if striker:
            if d.extras not in ['WD', 'NB']:
                # update both 'balls' and 'balls_faced' if present
                if hasattr(striker, 'balls'):
                    striker.balls = (striker.balls or 0) + 1
                if hasattr(striker, 'balls_faced'):
                    striker.balls_faced = (striker.balls_faced or 0) + 1
            striker.runs = (striker.runs or 0) + (d.runs or 0)

    if d.bowler_id:
        bowler = Player.query.get(d.bowler_id)
        if bowler:
            if d.extras not in ['WD', 'NB']:
                bowler.balls_bowled = (bowler.balls_bowled or 0) + 1
            bowler.runs_conceded = (bowler.runs_conceded or 0) + (d.runs or 0)
            if d.wicket:
                bowler.wickets = (bowler.wickets or 0) + 1

    db.session.commit()
    return jsonify({'status':'ok'})

@app.route('/api/match/<int:match_id>/score')
def api_get_score(match_id):
    summary = match_score_summary(match_id)

    deliveries_json = []
    for d in summary.get('deliveries', [])[-50:]:
        deliveries_json.append({
            'over': d.over,
            'ball': d.ball_in_over,
            'batsman': Player.query.get(d.striker_id).name if d.striker_id else "",
            'bowler': Player.query.get(d.bowler_id).name if d.bowler_id else "",
            'runs': d.runs,
            'extras': d.extras,
            'wicket': d.wicket,
            'wicket_type': d.wicket_type
        })

    return jsonify({
        'status': 'ok',
        'score': summary.get('score', {}),
        'deliveries': deliveries_json
    })

# -------------------------
# App entrypoint
# -------------------------

if __name__ == '__main__':
    app.run(debug=True)
