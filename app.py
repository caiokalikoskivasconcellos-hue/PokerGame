from flask import Flask, render_template, request, redirect, url_for, session
import uuid
import os
import time
from collections import Counter, defaultdict
from flask_socketio import SocketIO, emit, join_room, leave_room
from deck import Deck
from player import Player
from card import Card
from texasholdemgame import TexasHoldemGame
import math
from datetime import datetime
import threading
from datetime import datetime, timedelta

os.makedirs('static/avatars', exist_ok=True)
app = Flask(__name__)
app.secret_key = 'poker-secret-key'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

games = {}  # Stores game settings and player data
game_data = {}  # Enhanced tracking for player analysis
game_timers = {}  # Store timer threads

@app.route('/')
def home():
    return redirect(url_for('setup_game'))

def make_player_dict():
    """Factory for one player's detailed tracking data."""
    return {
        "hands": defaultdict(
            lambda: {
                "betting_rounds": {
                    "pre-flop": {"actions": [], "bet_amount": 0, "position": None},
                    "flop": {"actions": [], "bet_amount": 0},
                    "turn": {"actions": [], "bet_amount": 0},
                    "river": {"actions": [], "bet_amount": 0}
                },
                "hole_cards": None,
                "hand_strength": None,
                "position": None,
                "result": None,  # 'win', 'lose', 'fold'
                "pot_won": 0,
                "investment": 0,
                "went_to_showdown": False,
                "starting_stack": 0,
                "ending_stack": 0
            }
        ),
        "total_profit": 0,
        "total_buy_ins": 0,
        "style": None,
        "ai_summary": None,
        "stats": {
            "vpip": 0,  # Voluntarily Put $ In Pot
            "pfr": 0,   # Pre-Flop Raise
            "aggression_factor": 0,
            "aggression_frequency": 0,
            "fold_to_cbet": 0,
            "cbet_frequency": 0,
            "went_to_showdown": 0,
            "win_at_showdown": 0,
            "hands_played": 0,
            "hands_won": 0,
            "preflop_raise": 0,
            "three_bet": 0,  # Re-raise preflop
            "steal_attempt": 0,  # Raise from late position
            "fold_to_steal": 0,
            "total_bets": 0,
            "total_raises": 0,
            "total_calls": 0,
            "total_folds": 0,
            "total_checks": 0,
            "average_pot": 0,
            "biggest_pot_won": 0,
            "biggest_pot_lost": 0,
            "win_rate": 0
        },
        "risk_score": 0,
        "positional_stats": {
            "early": {"vpip": 0, "pfr": 0, "hands": 0},
            "middle": {"vpip": 0, "pfr": 0, "hands": 0},
            "late": {"vpip": 0, "pfr": 0, "hands": 0}
        }
    }

def start_game_timer(code, minutes):
    """Start a countdown timer for the game"""
    def timer_thread():
        end_time = datetime.now() + timedelta(minutes=minutes)
        
        while datetime.now() < end_time:
            if code not in games:  # Game ended
                return
                
            time_left = end_time - datetime.now()
            minutes_left = int(time_left.total_seconds() // 60)
            seconds_left = int(time_left.total_seconds() % 60)
            
            # Emit time update every second
            socketio.emit('time_update', {
                'minutes': minutes_left,
                'seconds': seconds_left,
                'total_seconds': int(time_left.total_seconds())
            }, room=code)
            
            time.sleep(1)
        
        # Time's up - end the game after current hand
        if code in games:
            games[code]['time_expired'] = True
            socketio.emit('time_expired', {}, room=code)
            print(f"Time expired for game {code}")
    
    thread = threading.Thread(target=timer_thread)
    thread.daemon = True
    thread.start()
    game_timers[code] = thread
    print(f"Started timer for {minutes} minutes for game {code}")

@app.route('/setup', methods=['GET', 'POST'])
def setup_game():
    error = None
    join_link = None
    if request.method == 'POST':
        try:
            max_players = int(request.form['max_players'])
            if max_players > 10:
                error = "Sorry, the maximum allowed players is 10."
                return render_template('setup.html', error=error)
            min_players = int(request.form['min_players'])
            time_limit = int(request.form['time_limit'])
            chips_per_dollar = int(request.form['chips_per_dollar'])
            buy_in = int(request.form['buy_in'])
            big_blind = int(request.form['big_blind'])
            small_blind = int(request.form['small_blind'])
            game_code = str(uuid.uuid4())[:6]
            deck = Deck()
            community_cards = [deck.deal_card() for i in range(5)]
            # Set all community cards to hidden initially
            for card in community_cards:
                card.visible = False
                
            games[game_code] = {
                'max_players': max_players,
                'min_players': min_players,
                'time_limit': time_limit,
                'chips_per_dollar': chips_per_dollar,
                'buy_in': buy_in,
                'big_blind': big_blind,
                'small_blind': small_blind,
                'players': [],
                'current_player_index': 0,
                'deck': deck,
                'community_cards': [card.to_dict() for card in community_cards],
                'current_highest_bet': 0,
                'last_raiser_index': None,
                'betting_round_active': True,
                'round_stage': 'pre-flop',  # pre-flop, flop, turn, river
                'hand': 1,
                'pots': [],
                'active_pot': 0,
                'dealer_position': 0,  # Track dealer button position
                'small_blind_pos': 1,  # Small blind is next after dealer
                'big_blind_pos': 2,    # Big blind is two after dealer
                'first_hand_completed': False,  # Track if first hand completed
                'time_expired': False,  # NEW: Time limit tracking
                'extend_votes': set(),     # NEW: Votes to extend time
                'buy_back_votes': set(),    # NEW: Votes to buy back in
                'total_voters': set(),
                'timer_active': True,
                "last_player": 0
            }
            
            # Initialize game_data for this game
            game_data[game_code] = {}
            
            join_link = url_for('join_game', code=game_code, _external=True)
            return render_template('setup.html', game_code=game_code, join_link=join_link)
        except (ValueError, KeyError):
            error = "Please ensure all fields are filled with valid numbers."

    return render_template('setup.html', error=error)

@app.route('/join/<code>', methods=['GET', 'POST'])
def join_game(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404

    error = None
    full = False

    if len(game['players']) >= game['max_players']:
        full = True
        return render_template('player_creation.html', code=code, full=full)

    if request.method == 'POST':
        name = request.form.get('name')
        avatar = request.files.get('avatar')

        if not name:
            error = "Name is required."
        else:
            if avatar:
                avatar_filename = f"{uuid.uuid4().hex}.png"
                avatar.save(os.path.join("static", "avatars", avatar_filename))
                avatar_path = f"avatars/{avatar_filename}"
            else:
                avatar_path = "avatars/default.png"

            player_id = str(uuid.uuid4())
            session['player_id'] = player_id
            session['game_code'] = code
            player = Player(name=name, money=float(game['buy_in']), number=len(game['players']) + 1, id=player_id, avatar=avatar_path, ready=False)
            # Don't deal cards yet - wait for game start
            game['players'].append(player.to_dict())
            games[code] = game
            
            # Initialize player tracking in game_data
            if code in game_data:
                game_data[code][name] = make_player_dict()
            
            session['player_id'] = player.id
            return redirect(url_for('lobby', code=code))
    return render_template('player_creation.html', code=code, error=error, full=full)

@app.route('/lobby/<code>')
def lobby(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404

    current_players = len(game['players'])
    min_players = game['min_players']

    if current_players < min_players:
        players_needed = min_players - current_players
        return render_template(
            'waiting_lobby.html',
            code=code,
            players=game['players'],
            players_needed=players_needed
        )
    else:
        return render_template(
            'lobby.html',
            code=code,
            players=game['players']
        )

@app.route('/start/<code>', methods=['POST'])
def start_game(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404

    player_id = session.get('player_id')
    if not player_id:
        return "Player session not found.", 400

    for player in game['players']:
        if player['id'] == player_id:
            player['ready'] = True

    if all(player.get('ready', False) for player in game['players']):
        # Start the game timer
        start_game_timer(code, game['time_limit'])
        
        # Initialize first hand
        game['deck'] = Deck()
        
        # Deal hole cards to players
        for player in game['players']:
            player['holecards'] = []
            for i in range(2):
                card = game['deck'].deal_card()
                card.visible = True
                player['holecards'].append(card.to_dict())
                
            # Initialize hand tracking in game_data
            if code in game_data and player['name'] in game_data[code]:
                player_data = game_data[code][player['name']]
                player_data['hands'][game['hand']]['starting_stack'] = player['money']
                player_data['hands'][game['hand']]['hole_cards'] = player['holecards']
                
                # Determine position
                player_index = game['players'].index(player)
                total_players = len(game['players'])
                if player_index <= 1:
                    position = "early"
                elif player_index <= total_players - 3:
                    position = "middle"
                else:
                    position = "late"
                player_data['hands'][game['hand']]['position'] = position
                player_data['positional_stats'][position]['hands'] += 1

        # Deal community cards (face down)
        community_cards = []
        for i in range(5):
            card = game['deck'].deal_card()
            card.visible = False
            community_cards.append(card.to_dict())
        game['community_cards'] = community_cards
        
        # POST BLINDS 
        sb_player = game['players'][game['small_blind_pos']]
        bb_player = game['players'][game['big_blind_pos']]
        
        sb_amount = min(game['small_blind'], sb_player['money'])
        bb_amount = min(game['big_blind'], bb_player['money'])
        
        sb_player['money'] -= sb_amount
        sb_player['current_bet'] = sb_amount
        bb_player['money'] -= bb_amount
        bb_player['current_bet'] = bb_amount
        
        # Track blind posts in game_data
        if code in game_data:
            if sb_player['name'] in game_data[code]:
                game_data[code][sb_player['name']]['hands'][game['hand']]['investment'] += sb_amount
            if bb_player['name'] in game_data[code]:
                game_data[code][bb_player['name']]['hands'][game['hand']]['investment'] += bb_amount
        
        # Set initial betting state
        game['current_highest_bet'] = bb_amount
        game['last_raiser_index'] = game['big_blind_pos']
        game['active_pot'] = sb_amount + bb_amount
        game['current_player_index'] = (game['big_blind_pos'] + 1) % len(game['players'])
        
        
        # Reset player states
        for player in game['players']:
            player['has_folded'] = False
            player['has_gone_all_in'] = False
            player['moved'] = False
            player['last_action'] = None
        
        print(f"Game {code} started with {len(game['players'])} players")
        print(f"Dealer: {game['dealer_position']}, SB: {game['small_blind_pos']}, BB: {game['big_blind_pos']}")
        print(f"Starting player index: {game['current_player_index']}")

        # Emit initial game state with blind information
        socketio.emit('new_hand_started', {
            'players': game['players'],
            'community_cards': game['community_cards'],
            'current_player_index': game['current_player_index'],
            'dealer_position': game['dealer_position'],
            'small_blind_pos': game['small_blind_pos'],
            'big_blind_pos': game['big_blind_pos'],
            'current_highest_bet': game['current_highest_bet'],
            'pot': game['active_pot'],
            'first_hand_completed': game['first_hand_completed']
        }, room=code)
        
        # Explicitly emit turn update
        current_player_id = game['players'][game['current_player_index']]['id']
        socketio.emit('turn_update', {
            'current_player_id': current_player_id
        }, room=code)
        
        return redirect(url_for('poker_game', code=code))
    else:
        return redirect(url_for('waiting_start', code=code))

@app.route('/waiting_start/<code>')
def waiting_start(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404

    player_id = session.get('player_id')
    if not player_id:
        return "Player session not found.", 400

    all_ready = all(player.get('ready', False) for player in game['players'])

    if all_ready:
        return redirect(url_for('poker_game', code=code))

    return render_template('waiting_start.html', code=code)

@app.route('/poker_game/<code>')
def poker_game(code):
    game = games.get(code)
    if not game:
        return "Game not found", 404
    player_id = session.get('player_id')
    if not player_id:
        return "Player session not found.", 400

    # Prepare players data with holecards visibility according to viewer
    players_data = []
    for p in game['players']:
        player = Player.from_dict(p)
        # Make cards visible only if this is the session player viewing
        if p['id'] == player_id:
            # Show actual hole cards (face up)
            for card in player.holecards:
                card.visible = True
        else:
            # Other players: hide hole cards (show back)
            for card in player.holecards:
                card.visible = False
        players_data.append(player.to_dict())

    return render_template("poker_game.html",
                       game=game,  
                       players=players_data,
                       current_player_id=game['players'][game['current_player_index']]['id'],
                       session_player_id=player_id,
                       code=code,
                       community_cards=game['community_cards'],
                       round_stage=game['round_stage'],
                       current_player_index=game['current_player_index'],
                       dealer_position=game['dealer_position'],
                       small_blind_pos=game['small_blind_pos'],
                       big_blind_pos=game['big_blind_pos'],
                       first_hand_completed=game['first_hand_completed'])

# NEW: Game over routes
@app.route('/game_over_time/<code>')
def game_over_time(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404
    
    reports = generate_player_reports(code)
    return render_template('game_over_time.html', 
                         code=code, 
                         game=game,
                         reports=reports)

@app.route('/game_over_buyin/<code>')
def game_over_buyin(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404
    
    reports = generate_player_reports(code)
    return render_template('game_over_buyin.html', 
                         code=code, 
                         game=game,
                         reports=reports)

@app.route('/continue_game/<code>', methods=['POST'])
def continue_game(code):
    game = games.get(code)
    if not game:
        return "Game not found.", 404
    
    # Reset game state for continuation
    game['time_expired'] = False
    
    # Reset vote counts using the new set format
    game['extend_votes'] = set()
    game['total_voters'] = set()
    
    # Start new timer with extended time
    extended_time = game['time_limit'] // 2
    start_game_timer(code, extended_time)
    
    # Instead of just redirecting, we need to continue the game properly
    # Start a new hand to continue playing
    socketio.start_background_task(start_new_hand, code)
    
    return redirect(url_for('poker_game', code=code))

### SOCKET.IO EVENTS ###

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")

@socketio.on('join_room')
def on_join_room(data):
    room = data['code']
    join_room(room)
    print(f"Client {request.sid} joined room {room}")
    
    # Send current game state to the joining client
    game = games.get(room)
    if game:
        emit('turn_update', {
            'current_player_id': game['players'][game['current_player_index']]['id']
        }, room=request.sid)
        
        # Send current stage
        emit('update_stage', {
            'stage': game['round_stage'],
            'temp_status': None
        }, room=request.sid)
        
        # Send current timer state if available
        if room in game_timers:
            # Calculate time left (this is approximate)
            time_left = game['time_limit'] * 60  # Convert to seconds
            minutes = time_left // 60
            seconds = time_left % 60
            emit('time_update', {
                'minutes': minutes,
                'seconds': seconds,
                'total_seconds': time_left
            }, room=request.sid)

def next_round_stage(code):
    game = games.get(code)
    if not game:
        return
    
    # Convert community cards to Card objects
    community_cards = [Card.from_dict(card) for card in game['community_cards']]
    
    # Stages in order
    stages = ['pre-flop', 'flop', 'turn', 'river']
    current_index = stages.index(game['round_stage'])
    
    if current_index < len(stages) - 1:
        next_stage = stages[current_index + 1]
        temp_status = f"Betting round over - dealing the {next_stage}"
        
        socketio.emit('update_stage', {
            'stage': game['round_stage'],
            'temp_status': temp_status
        }, room=code)
        
        socketio.sleep(2)
        
        # Advance to next stage
        game['round_stage'] = next_stage
        
        # Update community card visibility
        if next_stage == 'flop':
            for i in range(3):
                community_cards[i].visible = True
        elif next_stage == 'turn':
            community_cards[3].visible = True
        elif next_stage == 'river':
            community_cards[4].visible = True
            
        game['community_cards'] = [card.to_dict() for card in community_cards]
        
        # Emit updated community cards
        socketio.emit('update_community_cards', {
            'community_cards': game['community_cards']
        }, room=code)
            
        # Reset betting state
        game['last_raiser_index'] = None
        for player in game['players']:
            player['moved'] = False
        
        # Set starting player for this street
        if next_stage == 'flop':
            # Post-flop streets start with player after dealer
            game['current_player_index'] = (game['dealer_position'] + 1) % len(game['players'])
        else:
            # For turn and river, just continue from previous position
            game['current_player_index'] = game['current_player_index']
        
        # Skip folded/all-in players
        while True:
            current_player = game['players'][game['current_player_index']]
            if (not current_player.get('has_folded') and 
                not current_player.get('has_gone_all_in') and
                current_player['money'] > 0):  # NEW: Check if player has money
                break
            game['current_player_index'] = (game['current_player_index'] + 1) % len(game['players'])
        
        game['betting_round_active'] = True
        
        # Send updates
        socketio.emit('update_stage', {
            'stage': game['round_stage'],
            'temp_status': None
        }, room=code)
        
        socketio.emit('turn_update', {
            'current_player_id': game['players'][game['current_player_index']]['id'],
            'dealer_position': game['dealer_position'],
            'small_blind_pos': game['small_blind_pos'],
            'big_blind_pos': game['big_blind_pos']
        }, room=code)
    else:
        # Showdown - reveal all community cards
        community_cards = [Card.from_dict(card) for card in game['community_cards']]
        for card in community_cards:
            card.visible = True
        game['community_cards'] = [card.to_dict() for card in community_cards]
        
        socketio.emit('update_community_cards', {
            'community_cards': game['community_cards']
        }, room=code)
        socketio.emit('update_stage', {
            'stage': 'showdown',
            'temp_status': 'Showdown! All cards revealed'
        }, room=code)
        
        socketio.sleep(2)
        
        # Process showdown in background
        socketio.start_background_task(process_showdown, code)

def process_showdown(code):
    """Process showdown in a background task"""
    game = games.get(code)
    if not game:
        return
        
    # NEW: Make all hole cards visible during showdown
    for player in game['players']:
        for card in player['holecards']:
            card['visible'] = True
        # Calculate and attach hand description for display (mark folded players)
        if player.get('has_folded'):
            player['hand_description'] = 'Folded'
        else:
            get_hand(code, player)
    
    # NEW: Emit showdown cards FIRST to reveal everything
    socketio.emit('showdown_cards', {
        'players': game['players']
    }, room=code)
    
    socketio.emit('update_stage', {
        'stage': 'showdown',
        'temp_status': 'Showdown! All cards revealed'
    }, room=code)
    
    # NEW: Wait 5 seconds for players to see all cards
    socketio.sleep(5)
    
    # Now process the pots and winners
    create_pots(code)
    winners_info = []
    winner_ids = set()
    
    # Process each pot
    for pot in game['pots']:
        pot_players = [p for p in game['players'] if p['id'] in pot['players'] and not p['has_folded']]
        
        # Calculate hand scores for all players in this pot
        for player in pot_players:
            if player["has_folded"]:
                continue
            get_hand(code, player)
        
        # Find winners for this pot
        winners = []
        winnerhand = []
        winnerscore = -1
        
        for player in pot_players:
            if player['handscores'][0] > winnerscore:
                winners = [player]
                winnerhand = player['handscores']
                winnerscore = player['handscores'][0]
            elif player['handscores'][0] == winnerscore:    
                # Tie-breaker: compare kickers
                for i in range(len(winnerhand)):
                    if player['handscores'][i] > winnerhand[i]:
                        winners = [player]
                        winnerhand = player['handscores']
                        winnerscore = player['handscores'][0]
                        break
                    elif player['handscores'][i] < winnerhand[i]:
                        break
                else:
                    # Complete tie
                    winners.append(player)
        
        print(f"Pot winners: {', '.join((player['name'] for player in winners))}")

        # Split pot among winners
        pot_per_winner = pot["amount"] / len(winners)
        
        for winner in winners:
            winner['money'] += pot_per_winner
            winners_info.append({
                'player_id': winner['id'],
                'amount': pot_per_winner,
                'pot_index': game['pots'].index(pot)
            })
            winner_ids.add(winner['id'])
            
            # Update game_data for winners
            if code in game_data and winner['name'] in game_data[code]:
                player_data = game_data[code][winner['name']]
                current_hand = player_data['hands'][game['hand']]
                current_hand['result'] = 'win'
                current_hand['pot_won'] += pot_per_winner
                current_hand['ending_stack'] = winner['money']
                player_data['total_profit'] += pot_per_winner - current_hand['investment']
                player_data['stats']['hands_won'] += 1
                player_data['stats']['biggest_pot_won'] = max(player_data['stats']['biggest_pot_won'], pot_per_winner)

    # Update game_data for losers
    for player in game['players']:
        if player['id'] not in winner_ids:
            if code in game_data and player['name'] in game_data[code]:
                player_data = game_data[code][player['name']]
                current_hand = player_data['hands'][game['hand']]
                if not player['has_folded']:
                    current_hand['result'] = 'lose'
                current_hand['ending_stack'] = player['money']
                loss_amount = current_hand['investment']
                player_data['total_profit'] -= loss_amount
                player_data['stats']['biggest_pot_lost'] = max(player_data['stats']['biggest_pot_lost'], loss_amount)

    # NEW: Mark first hand as completed
    game['first_hand_completed'] = True

    # NEW: Emit winner information after showing cards for 5 seconds
    socketio.emit('showdown_results', {
        'winners': winners_info
    }, room=code)
    
    # Calculate and emit player reports if game is ending
    players_with_chips = [p for p in game['players'] if p['money'] > 0 and not p.get('sit_out_next_hand', False)]
    
    # Wait for winner animation to complete (5 seconds)
    socketio.sleep(5)

    # NEW: Check for time expiration
    if game.get('time_expired'):
        socketio.emit('game_over_time', {}, room=code)
        return
    
    if len(players_with_chips) == 1:
        socketio.emit('game_over_buyin', {}, room=code)
        return
    
    # Start new betting round
    start_new_hand(code)

def get_hand(code, p):
    game = games.get(code)
    if not game:
        return
    p['handscores'] = calc_hand(game['community_cards'], p['holecards'])
    # NEW: Add hand description for display
    p['hand_description'] = get_hand_description(p['handscores'])
    
    # Update game_data with hand strength
    if code in game_data and p['name'] in game_data[code]:
        game_data[code][p['name']]['hands'][game['hand']]['hand_strength'] = p['handscores'][0]

def get_hand_description(hand_score):
    """Convert hand score to human readable description"""
    if not hand_score:
        return "No hand"
    
    hand_rank = hand_score[0]
    descriptions = {
        10: "Royal Flush",
        9: "Straight Flush",
        8: "Four of a Kind", 
        7: "Full House",
        6: "Flush",
        5: "Straight",
        4: "Three of a Kind",
        3: "Two Pair",
        2: "One Pair",
        1: "High Card"
    }
    return descriptions.get(hand_rank, "Unknown Hand")

def calc_hand(community_cards, hole_cards):
        com_cards = [Card.from_dict(card) for card in community_cards]
        h_cards = [Card.from_dict(card) for card in hole_cards]
        return_list = []
        s = False
        hc = True
        all_cards = com_cards + h_cards
        all_cards.sort(key=lambda card: card.rank)
        rank_counts = Counter(card.rank for card in all_cards)
        suit_counts = Counter(card.suit for card in all_cards)
        fk = 4 in rank_counts.values()
        fh = 3 in rank_counts.values() and 2 in rank_counts.values()
        f = any(count >= 5 for count in suit_counts.values())
        flush_suit = next((suit for suit, count in suit_counts.items() if count >= 5), None)
        tk = 3 in rank_counts.values()
        tp = list(rank_counts.values()).count(2) >= 2
        p = 2 in rank_counts.values()
        suits = {}
        royal_ranks = {10, 11, 12, 13, 14}
        for card in all_cards:
            suits.setdefault(card.suit, []).append(card)
        rf = False
        for suited_cards in suits.values():
            suited_ranks = set(card.rank for card in suited_cards)
            if royal_ranks.issubset(suited_ranks):
                rf = True
                break
        count = 1
        duplicates = 0
        sf = False
        for i in range(len(all_cards)-1, 0, -1):
            if count == 5:
                s = True
                sstart = i
                break
            if all_cards[i-1].rank - all_cards[i].rank == -1:
                count += 1
            else:
                if all_cards[i-1].rank - all_cards[i].rank != 0:
                    count = 1
                else:
                    duplicates += 1
        if s:
            flush_count = Counter(card.suit for card in all_cards[sstart:sstart + 5 + duplicates])
            if 5 in flush_count.values():
                sf = True
        
        if rf:
            return_list.append(10)
            return_list.append(10+11+12+13+14)
            return_list.append(0)
            return return_list
        elif sf:
            return_list.append(9)
            return_list.append(all_cards[sstart + 4].rank)
            return return_list
        elif fk:
            return_list.append(8)
            fk_rank = next((rank for rank, count in rank_counts.items() if count == 4), None)
            kicker = max(card.rank for card in all_cards if card.rank != fk_rank)
            return_list.append(fk_rank)
            return_list.append(kicker)
            return return_list
        elif fh:
            return_list.append(7)
            return_list.append(next((rank for rank, count in rank_counts.items() if count == 3), None))
            return_list.append(max((rank for rank, count in rank_counts.items() if count == 2), default=None))
            return return_list
        elif f:
            return_list.append(6)
            flush_cards = [card for card in all_cards if card.suit == flush_suit]
            flush_cards_sorted = sorted(flush_cards, key=lambda c: c.rank, reverse=True)
            return_list.append(flush_cards_sorted[0].rank)
            return_list.append(flush_cards_sorted[1].rank)
            return_list.append(flush_cards_sorted[2].rank)
            return_list.append(flush_cards_sorted[3].rank)
            return_list.append(flush_cards_sorted[4].rank)
            return return_list
        elif s:
            return_list.append(5)
            return_list.append(all_cards[sstart + 4].rank)
            return return_list
        elif tk:
            return_list.append(4)
            trip_rank = max((rank for rank, count in rank_counts.items() if count == 3), default=None)
            return_list.append(trip_rank)
            kickers = [card.rank for card in all_cards if card.rank != trip_rank]
            kickers = sorted(set(kickers), reverse=True)[:2]
            return_list.extend(kickers)
            return return_list
        elif tp:
            pairs = sorted((rank for rank, count in rank_counts.items() if count == 2), reverse=True)
            pair_rank1, pair_rank2 = pairs[:2]
            kicker = max(card.rank for card in all_cards if card.rank != pair_rank1 and card.rank != pair_rank2)
            return_list.append(3)
            return_list.append(pair_rank1)
            return_list.append(pair_rank2)
            return_list.append(kicker)
            return return_list
        elif p:
            return_list.append(2)
            pair_rank = max((rank for rank, count in rank_counts.items() if count == 2), default=None)
            return_list.append(pair_rank)
            kickers = [card.rank for card in all_cards if card.rank != pair_rank]
            kickers = sorted(set(kickers), reverse=True)[:3]
            return_list.extend(kickers)
            return return_list
        elif hc:
            return_list.append(1)
            return_list.append(all_cards[-1].rank)
            return_list.append(all_cards[-2].rank)
            return_list.append(all_cards[-3].rank)
            return_list.append(all_cards[-4].rank)
            return_list.append(all_cards[-5].rank)
            return return_list
    
        
def create_pots(code):
    game = games.get(code)
    if not game:
        return
    game['pots'] = []  # reset pots list

    # Get all players who still have money in the pot and are eligible
    active_players = [p for p in game['players'] if p['current_bet'] > 0 and not p.get('has_folded', False)]
    if not active_players:
        return

    # Sort players by their current bet (ascending)
    active_players.sort(key=lambda p: p['current_bet'])
    
    previous_bet = 0
    for i, player in enumerate(active_players):
        current_bet = player['current_bet']
        if current_bet <= previous_bet:
            continue
            
        # Calculate how much each player contributes to this side pot
        pot_amount = 0
        pot_players = []
        
        for p in game['players']:
            if p['current_bet'] >= current_bet and not p.get('has_folded', False):
                contribution = min(current_bet - previous_bet, p['current_bet'] - previous_bet)
                pot_amount += contribution
                pot_players.append(p['id'])
        
        if pot_amount > 0:
            game['pots'].append({
                "amount": pot_amount,
                "players": pot_players  # players eligible for this pot
            })
        
        previous_bet = current_bet

    # After creating pots, reset all current_bets to 0 for next hand
    for player in game['players']:
        player['current_bet'] = 0

def start_new_hand(code):
    game = games.get(code)
    if not game:
        return

    print(f"Starting new hand for game {code}")
    game['hand'] += 1

    # Reset all current bets
    for player in game['players']:
        player['current_bet'] = 0

    # Reset deck before any cards are dealt
    game['deck'] = Deck()

    # In start_new_hand function, before dealing cards:
    for player in game['players']:
        # Check if player has bought back in and should get money
        if player.get('buy_back_amount'):
            player['money'] = player['buy_back_amount']
            player['buy_back_amount'] = None  # Clear the buy back amount
            player['sit_out_next_hand'] = False
        
        if (player['money'] > 0 and 
            not player.get('is_out', False) and 
            not player.get('sit_out_next_hand', False)):
            # Deal new hole cards
            player['holecards'] = []
            for i in range(2):
                card = game['deck'].deal_card()
                card.visible = True
                player['holecards'].append(card.to_dict())
        
            # Reset player status
            player['has_folded'] = False
            player['has_gone_all_in'] = False
            player['moved'] = False
            player['last_action'] = None
            player['hand_description'] = None
            player['sitting_out'] = False
        
            # Update game_data for new hand
            if code in game_data and player['name'] in game_data[code]:
                player_data = game_data[code][player['name']]
                player_data['hands'][game['hand']]['starting_stack'] = player['money']
                player_data['hands'][game['hand']]['hole_cards'] = player['holecards']
                player_data['stats']['hands_played'] += 1
            
                # Determine position
                player_index = game['players'].index(player)
                total_players = len(game['players'])
                if player_index <= 1:
                    position = "early"
                elif player_index <= total_players - 3:
                    position = "middle"
                else:
                    position = "late"

                player_data['hands'][game['hand']]['position'] = position
                player_data['positional_stats'][position]['hands'] += 1
        else:
            # If player chose to sit out next hand, mark them as sitting out for this hand
            if player.get('sit_out_next_hand', False):
                player['sitting_out'] = True
                player['is_out'] = False  # Ensure they're not marked as out
    # Check for game over conditions
    players_with_chips = [p for p in game['players'] if p['money'] > 0 and not p.get('sit_out_next_hand', False)]
    if len(players_with_chips) == 1:
        print(f"Game over - only one player with chips: {players_with_chips[0]['name']}")
        winner = players_with_chips[0]
        socketio.emit('game_over', {
            'winner_id': winner['id'],
            'winner_name': winner['name']
        }, room=code)
        
        # Generate final reports
        reports = generate_player_reports(code)
        socketio.emit('game_analysis_report', {
            'reports': reports
        }, room=code)
        return
    # Move dealer button to next ACTIVE player (excluding sitting out players)
    def find_next_active(start_idx):
        idx = start_idx % len(game['players'])
        checked = 0
        while checked < len(game['players']):
            player = game['players'][idx]
            if not player.get('is_out', False) and player['money'] > 0 and not player.get('sit_out_next_hand', False):
                return idx
            idx = (idx + 1) % len(game['players'])
            checked += 1
        return start_idx  # fallback

    # Advance dealer position once
    game['dealer_position'] = find_next_active(game['dealer_position'] + 1)
    
    # Set blind positions relative to dealer (excluding sitting out players)
    game['small_blind_pos'] = find_next_active(game['dealer_position'] + 1)
    game['big_blind_pos'] = find_next_active(game['small_blind_pos'] + 1)

    print(f"Dealer: {game['dealer_position']}, SB: {game['small_blind_pos']}, BB: {game['big_blind_pos']}")

    # Post blinds (only for non-sitting out players)
    sb_player = game['players'][game['small_blind_pos']]
    bb_player = game['players'][game['big_blind_pos']]
    
    sb_amount = min(game['small_blind'], sb_player['money'])
    bb_amount = min(game['big_blind'], bb_player['money'])
    
    sb_player['money'] -= sb_amount
    sb_player['current_bet'] = sb_amount
    bb_player['money'] -= bb_amount
    bb_player['current_bet'] = bb_amount
    
    # Set initial pot
    game['active_pot'] = sb_amount + bb_amount
    
    # Reset community cards (face down)
    community_cards = []
    for i in range(5):
        card = game['deck'].deal_card()
        card.visible = False
        community_cards.append(card.to_dict())
    game['community_cards'] = community_cards

    # Set starting player (after big blind) - excluding sitting out players
    game['current_player_index'] = find_next_active(game['big_blind_pos'] + 1)
    
    # Reset betting state
    game['current_highest_bet'] = bb_amount
    game['last_raiser_index'] = game['big_blind_pos']
    game['betting_round_active'] = True
    game['round_stage'] = 'pre-flop'
    game['pots'] = []

    print(f"Starting player index: {game['current_player_index']}")

    # Emit game state
    socketio.emit('new_hand_started', {
        'players': game['players'],
        'community_cards': game['community_cards'],
        'current_player_index': game['current_player_index'],
        'dealer_position': game['dealer_position'],
        'small_blind_pos': game['small_blind_pos'],
        'big_blind_pos': game['big_blind_pos'],
        'current_highest_bet': game['current_highest_bet'],
        'pot': game['active_pot'],
        'first_hand_completed': game['first_hand_completed']
    }, room=code)
    
    # Start betting
    socketio.emit('turn_update', {
        'current_player_id': game['players'][game['current_player_index']]['id']
    }, room=code)


@socketio.on('player_action')
def handle_player_action(data):
    code = data['code']
    player_id = data['player_id']
    action = data['action']
    amount = data.get('amount', 0)
    print(f"[ACTION] Player {player_id} does {action.upper()} with amount {amount} in game {code}")
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    if not game.get('betting_round_active'):
        emit('error', {'msg': 'Betting round not active'})
        return

    player = next((p for p in game['players'] if p['id'] == player_id), None)
    if not player:
        emit('error', {'msg': 'Player not found.'})
        return

    # Check if player is all-in or has no money
    if player.get('has_gone_all_in') or player['money'] <= 0:
        emit('error', {'msg': 'You are all-in and cannot act.'})
        return
    # In handle_player_action function, add sitting_out check
    if player.get('sitting_out', False):
        emit('error', {'msg': 'You are sitting out this hand.'})
        return

    current_index = game['current_player_index']
    current_player = game['players'][current_index]

    if player['id'] != current_player['id']:
        emit('error', {'msg': 'Not your turn!'})
        return

    # Update game_data with player action
    if code in game_data and player['name'] in game_data[code]:
        player_data = game_data[code][player['name']]
        current_hand = player_data['hands'][game['hand']]
        current_round = current_hand['betting_rounds'][game['round_stage']]
        
        # Record action
        current_round['actions'].append({
            'action': action,
            'amount': amount if amount is not None else 0,
            'timestamp': time.time(),
            'pot_size': game['active_pot'],
            'current_bet': game['current_highest_bet']
        })
        
        # Update statistics
        stats = player_data['stats']
        if action == 'fold':
            stats['total_folds'] += 1
        elif action == 'check':
            stats['total_checks'] += 1
        elif action == 'call':
            stats['total_calls'] += 1
            # For call action, calculate the actual amount called
            to_call = game['current_highest_bet'] - player['current_bet']
            call_amount = min(to_call, player['money']) if to_call > 0 else 0
            current_hand['investment'] += call_amount
        elif action == 'raise':
            stats['total_raises'] += 1
            stats['total_bets'] += 1
            current_hand['investment'] += amount
            
            # Check for pre-flop raise
            if game['round_stage'] == 'pre-flop':
                stats['preflop_raise'] += 1

    if action == 'fold':
        player['has_folded'] = True
    elif action == 'check':
    # Player can only check if they've matched the current bet
        if player['current_bet'] < game['current_highest_bet']:
            emit('error', {'msg': f'Cannot check - must call {game["current_highest_bet"] - player["current_bet"]} more'})
            return
        player['moved'] = True

    elif action == 'call':
        to_call = game['current_highest_bet'] - player['current_bet']
        if to_call <= 0:
            emit('error', {'msg': 'Nothing to call.'})
            return
        if player['money'] >= to_call:
            player['money'] -= to_call
            player['current_bet'] += to_call
            player['moved'] = True
            game['active_pot'] += to_call
        else:
            # All-in call
            player['current_bet'] += player['money']
            game['active_pot'] += player['money']
            player['money'] = 0
            player['has_gone_all_in'] = True
            player['moved'] = True

    elif action == 'raise':
        to_call = game['current_highest_bet'] - player['current_bet']
        total_bet = to_call + amount
        if amount <= 0:
            emit('error', {'msg': 'Raise amount must be greater than 0.'})
            return
        if player['money'] >= total_bet:
            player['money'] -= total_bet
            player['current_bet'] += total_bet
            game['current_highest_bet'] = player['current_bet']
            game['last_raiser_index'] = game['current_player_index']
            player['moved'] = True
            game['active_pot'] += total_bet
        else:
            emit('error', {'msg': 'Not enough chips to raise.'})
            return

    else:
        emit('error', {'msg': 'Invalid action.'})
        return

    # Update player's last action text and chips for UI
    text = action.upper() if action != 'raise' else f"RAISES TO {player['current_bet']}"
    player['last_action'] = text
    
    # Emit to ALL clients in the room
    emit('update_action', {
        'player_id': player_id,
        'action_text': text,
        'money': player['money'],
        'pot': game['active_pot']
    }, room=code)
    
    print(f"Emitted update_action for player {player_id} in room {code}")

    # If only one player can still act (everyone else folded or all-in), skip directly to showdown
    

    # Advance to next active player (excluding sitting out and folded players)
    total_players = len(game['players'])
    next_index = (current_index + 1) % total_players

    skipped_players = 0
    while skipped_players < total_players:
        next_player = game['players'][next_index]
        if (not next_player.get('has_folded') and 
            not next_player.get('has_gone_all_in') and 
            not next_player.get('sitting_out', False) and  # ADDED: Check if not sitting out
            next_player['money'] > 0):  # NEW: Check if player has money
            break
        next_index = (next_index + 1) % total_players
        skipped_players += 1

    game['current_player_index'] = next_index

    # Check if all active players have matched the bet
    # Recompute these AFTER the action, because money/all-in status may have changed
    active_players = [
        p for p in game['players']
        if not p.get('has_folded') and not p.get('sitting_out', False)
    ]
    players_can_act = [
        p for p in active_players
        if (not p.get('has_gone_all_in')) and p.get('money', 0) > 0
    ]

    # Check if all active players have matched the bet
    all_matched = True
    for p in players_can_act:
        if p['current_bet'] < game['current_highest_bet'] or not p.get('moved'):
            all_matched = False
            break

    # If the betting round is complete AND no further betting is possible, go straight to showdown
    no_more_betting_possible = (len(active_players) > 1 and len(players_can_act) <= 1)

    if all_matched and no_more_betting_possible:
        game['betting_round_active'] = False
        game['round_stage'] = 'showdown'

        # Reveal all community cards before showdown
        community_cards = [Card.from_dict(card) for card in game['community_cards']]
        for card in community_cards:
            card.visible = True
        game['community_cards'] = [card.to_dict() for card in community_cards]

        socketio.emit('update_community_cards', {
            'community_cards': game['community_cards']
        }, room=code)
        socketio.emit('update_stage', {
            'stage': 'showdown',
            'temp_status': 'No further betting possible - proceeding to showdown'
        }, room=code)

        socketio.start_background_task(process_showdown, code)
        return

    # Existing behavior
    if all_matched:
        game['betting_round_active'] = False
        socketio.start_background_task(next_round_stage, code)
    else:
        emit('turn_update', {
            'current_player_id': game['players'][next_index]['id']
        }, room=code)


@socketio.on('toggle_sit_out')
def handle_toggle_sit_out(data):
    code = data['code']
    player_id = data['player_id']
    sit_out = data['sit_out']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    player = next((p for p in game['players'] if p['id'] == player_id), None)
    if not player:
        emit('error', {'msg': 'Player not found.'})
        return
        
    # Update player's sit out next hand status (not current hand)
    player['sit_out_next_hand'] = sit_out
    
    # Broadcast the update to all clients
    emit('player_sit_out_updated', {
        'player_id': player_id,
        'sit_out_next_hand': sit_out
    }, room=code)

# NEW: Socket event for buying back in
@socketio.on('buy_back_in')
def handle_buy_back(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    player = next((p for p in game['players'] if p['id'] == player_id), None)
    if not player:
        emit('error', {'msg': 'Player not found.'})
        return
    
    # Check if player has no money
    if player['money'] > 0:
        emit('error', {'msg': 'You still have chips, no need to buy back in.'})
        return
    
    # Add buy-in amount to player's next hand money
    player['buy_back_amount'] = game['buy_in']
    player['is_out'] = False
    player['sit_out_next_hand'] = True  # Will sit out current hand
    
    # Update game_data with buy-in information
    if code in game_data and player['name'] in game_data[code]:
        game_data[code][player['name']]['total_buy_ins'] = game_data[code][player['name']].get('total_buy_ins', 0) + game['buy_in']
    
    # Broadcast the update
    emit('player_bought_back', {
        'player_id': player_id,
        'new_money': 0  # Still 0 for current hand
    }, room=code)
    
    # Update the player's display
    emit('update_action', {
        'player_id': player_id,
        'action_text': 'BOUGHT BACK IN (Plays Next Hand)',
        'money': 0,  # Still shows 0 for current hand
        'pot': game['active_pot']
    }, room=code)

@socketio.on('buy_back_in_2')
def handle_buy_back(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    player = next((p for p in game['players'] if p['id'] == player_id), None)
    if not player:
        emit('error', {'msg': 'Player not found.'})
        return
    
    # Check if player has no money
    if player['money'] > 0:
        emit('error', {'msg': 'You still have chips, no need to buy back in.'})
        return
    
    # Add buy-in amount to player's next hand money
    player['buy_back_amount'] = game['buy_in']
    player['is_out'] = False
    player['sit_out_next_hand'] = False  # Will sit out current hand
    
    # Update game_data with buy-in information
    if code in game_data and player['name'] in game_data[code]:
        game_data[code][player['name']]['total_buy_ins'] = game_data[code][player['name']].get('total_buy_ins', 0) + game['buy_in']
    
    # Broadcast the update
    emit('player_bought_back', {
        'player_id': player_id,
        'new_money': 0  # Still 0 for current hand
    }, room=code)
    
    # Update the player's display
    emit('update_action', {
        'player_id': player_id,
        'action_text': 'BOUGHT BACK IN (Plays Next Hand)',
        'money': 0,  # Still shows 0 for current hand
        'pot': game['active_pot']
    }, room=code)
   
# Socket event for voting to extend time
@socketio.on('vote_buy_in')
def handle_vote_buy_in(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    # Initialize vote counts if they don't exist
    if 'buy_back_votes' not in game:
        game['buy_back_votes'] = set()  # Use set to track unique players
    if 'total_voters' not in game:
        game['total_voters'] = set()
        
    game['buy_back_votes'].add(player_id)
    game['total_voters'].add(player_id)
    
    total_players = len(game['players'])
    buy_back_count = len(game['buy_back_votes'])
    
    print(f"Extend vote received from {player_id}: {buy_back_count}/{total_players} players voted to extend")
    
    # Check if all players have voted
    if len(game['total_voters']) >= total_players:
        process_voting_result_b(code)
    else:
        # Not all players have voted yet
        emit('vote_update', {
            'buy_back_count': buy_back_count,
            'total_players': total_players
        }, room=code)

@socketio.on('vote_end_game_b')
def handle_vote_end_game_b(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    # Initialize vote counts if they don't exist
    if 'total_voters' not in game:
        game['total_voters'] = set()
    if 'extend_votes' not in game:
        game['buy_back_votes'] = set()
        
    # Remove from extend votes if they were there
    if player_id in game['buy_back_votes']:
        game['buy_back_votes'].remove(player_id)
    
    game['total_voters'].add(player_id)
    
    total_players = len(game['players'])
    buy_back_count = len(game['extend_votes'])
    
    print(f"End game vote received from {player_id}: {buy_back_count} players voted to extend")
    
    # Check if all players have voted
    if len(game['total_voters']) >= total_players:
        process_voting_result_b(code)
    else:
        # Not all players have voted yet
        emit('vote_update', {
            'buy_back_count': buy_back_count,
            'total_players': total_players
        }, room=code)

def process_voting_result_b(code):
    """Process the voting result after all players have voted"""
    game = games.get(code)
    if not game:
        return
    
    buy_back_count = len(game.get('buy_back_votes', set()))
    total_players = len(game['players'])
    
    print(f"Voting complete: {buy_back_count}/{total_players} players voted to extend")
    
    if buy_back_count >= 3:  # At least 3 players want to extend
        # Get the set of player IDs who voted to extend
        players_in_ids = game['buy_back_votes']
        
        # Filter players - keep only those who voted to extend
        game['players'][:] = [p for p in game['players'] if p['id'] in players_in_ids]

        # Ensure busted players are funded for the next hand
        for player in game['players']:
            if player['money'] <= 0:
                player['buy_back_amount'] = game['buy_in']
                player['sit_out_next_hand'] = False
        
        
        # Reset vote counts
        game['buy_back_votes'] = set()
        game['total_voters'] = set()
        # Start a new hand to continue the game
        socketio.start_background_task(start_new_hand, code)

        
        # Send time_extended to the game room (all connected clients will get it)
        # But only extending players will actually be in the game
        emit('game_extended', {
        }, room=code)
        print(f"Game extended for {buy_back_count} players, starting new hand")
    else:
        # Not enough votes to extend - end the game for everyone
        emit('end_game_b', {
            'buy_back_count': buy_back_count,
            'total_players': total_players
        }, room=code)
        print(f"Game ended - only {buy_back_count} players voted to extend")


# Socket event for voting to extend time
@socketio.on('vote_extend_time')
def handle_vote_extend_time(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    # Initialize vote counts if they don't exist
    if 'extend_votes' not in game:
        game['extend_votes'] = set()  # Use set to track unique players
    if 'total_voters' not in game:
        game['total_voters'] = set()
        
    game['extend_votes'].add(player_id)
    game['total_voters'].add(player_id)
    
    total_players = len(game['players'])
    extend_count = len(game['extend_votes'])
    
    print(f"Extend vote received from {player_id}: {extend_count}/{total_players} players voted to extend")
    
    # Check if all players have voted
    if len(game['total_voters']) >= total_players:
        process_voting_result_s(code)
    else:
        # Not all players have voted yet
        emit('vote_update', {
            'extend_count': extend_count,
            'total_players': total_players
        }, room=code)

@socketio.on('vote_end_game_s')
def handle_vote_end_game_s(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    # Initialize vote counts if they don't exist
    if 'total_voters' not in game:
        game['total_voters'] = set()
    if 'extend_votes' not in game:
        game['extend_votes'] = set()
        
    # Remove from extend votes if they were there
    if player_id in game['extend_votes']:
        game['extend_votes'].remove(player_id)
    
    game['total_voters'].add(player_id)
    
    total_players = len(game['players'])
    extend_count = len(game['extend_votes'])
    
    print(f"End game vote received from {player_id}: {extend_count} players voted to extend")
    
    # Check if all players have voted
    if len(game['total_voters']) >= total_players:
        process_voting_result_s(code)
    else:
        # Not all players have voted yet
        emit('vote_update', {
            'extend_count': extend_count,
            'total_players': total_players
        }, room=code)

def process_voting_result_s(code):
    """Process the voting result after all players have voted"""
    game = games.get(code)
    if not game:
        return
    
    extend_count = len(game.get('extend_votes', set()))
    total_players = len(game['players'])
    
    print(f"Voting complete: {extend_count}/{total_players} players voted to extend")
    
    if extend_count >= 3:  # At least 3 players want to extend
        # Get the set of player IDs who voted to extend
        players_in_ids = game['extend_votes']
        
        # Filter players - keep only those who voted to extend
        game['players'][:] = [p for p in game['players'] if p['id'] in players_in_ids]
        
        # Reset the timer with extended time
        extended_time = game['time_limit'] // 2
        start_game_timer(code, extended_time)
        game['time_expired'] = False
        
        # Reset vote counts
        game['extend_votes'] = set()
        game['total_voters'] = set()
        
        # Start a new hand to continue the game
        socketio.start_background_task(start_new_hand, code)
        
        # Send time_extended to the game room (all connected clients will get it)
        # But only extending players will actually be in the game
        emit('time_extended', {
            'extended_minutes': extended_time
        }, room=code)
        
        print(f"Game extended for {extend_count} players, starting new hand")
    else:
        # Not enough votes to extend - end the game for everyone
        emit('end_game_s', {
            'extend_count': extend_count,
            'total_players': total_players
        }, room=code)
        print(f"Game ended - only {extend_count} players voted to extend")

@socketio.on('turn_update')
def handle_turn_update(data):
    room = data['code']
    current_player_id = data['current_player_id']
    emit('turn_update', {'current_player_id': current_player_id}, room=room)
    
@socketio.on('start_betting_round')
def start_betting_round(data):
    code = data['code']
    game = games[code]

    game['last_raiser_index'] = None
    game['current_player_index'] = 0
    game['betting_round_active'] = True

    for player in game['players']:
        player['has_folded'] = False
        player['has_gone_all_in'] = False

    emit('turn_update', {
        'current_player_id': game['players'][0]['id']
    }, room=code)

# NEW: Socket event for requesting personal analysis during game
@socketio.on('request_personal_analysis')
def handle_personal_analysis(data):
    code = data['code']
    player_id = data['player_id']
    
    game = games.get(code)
    if not game:
        emit('error', {'msg': 'Game not found.'})
        return
        
    player = next((p for p in game['players'] if p['id'] == player_id), None)
    if not player:
        emit('error', {'msg': 'Player not found.'})
        return
    
    # Generate report for this player only
    if code in game_data and player['name'] in game_data[code]:
        player_data = game_data[code][player['name']]
        player_data = calculate_player_statistics(player_data, player['name'])
        
        # Generate playing style
        style, player_type, risk_score = generate_playing_style(player_data)
        player_data['style'] = style
        player_data['risk_score'] = risk_score
        
        # Generate personal summary
        stats = player_data['stats']
        summary = f"""
Player: {player['name']}
Playing Style: {style} ({player_type})
Risk Score: {risk_score:.1f}/100

Key Statistics:
- VPIP: {stats['vpip']:.1f}% (Voluntarily Put $ In Pot)
- PFR: {stats['pfr']:.1f}% (Pre-Flop Raise)
- Aggression Frequency: {stats['aggression_frequency']:.1f}%
- Aggression Factor: {stats['aggression_factor']:.1f}
- Hands Played: {stats['hands_played']}
- Win Rate: {stats['win_rate']:.1f}%
- Total Profit: ${player_data['total_profit']:.2f}
- Total Buy-ins: ${player_data.get('total_buy_ins', 0):.2f}

Positional Analysis:
- Early Position: VPIP {player_data['positional_stats']['early']['vpip']:.1f}%, PFR {player_data['positional_stats']['early']['pfr']:.1f}%
- Middle Position: VPIP {player_data['positional_stats']['middle']['vpip']:.1f}%, PFR {player_data['positional_stats']['middle']['pfr']:.1f}%
- Late Position: VPIP {player_data['positional_stats']['late']['vpip']:.1f}%, PFR {player_data['positional_stats']['late']['pfr']:.1f}%

Action Distribution:
- Raises: {stats['total_raises']}
- Calls: {stats['total_calls']}
- Checks: {stats['total_checks']}
- Folds: {stats['total_folds']}

Notable Achievements:
- Biggest Pot Won: ${stats['biggest_pot_won']:.2f}
- Biggest Pot Lost: ${stats['biggest_pot_lost']:.2f}
- Average Pot: ${stats['average_pot']:.2f}
"""
        
        # Send personal report to this player only
        emit('personal_analysis_report', {
            'player_name': player['name'],
            'style': style,
            'player_type': player_type,
            'risk_score': risk_score,
            'summary': summary,
            'stats': stats,
            'positional_stats': player_data['positional_stats'],
            'total_profit': player_data['total_profit'],
            'total_buy_ins': player_data.get('total_buy_ins', 0)
        }, room=request.sid)

def calculate_player_statistics(player_data, player_name):
    """Calculate comprehensive player statistics from tracked data"""
    stats = player_data['stats']
    hands = player_data['hands']
    
    if not hands:
        return player_data
    
    total_hands = len(hands)
    stats['hands_played'] = total_hands
    
    # Calculate VPIP (Voluntarily Put $ In Pot)
    vpip_hands = 0
    for hand_num, hand_data in hands.items():
        preflop_actions = hand_data['betting_rounds']['pre-flop']['actions']
        # Count if player voluntarily put money in pot (not including blinds)
        voluntary_actions = [a for a in preflop_actions if a['action'] in ['call', 'raise']]
        if voluntary_actions:
            vpip_hands += 1
    
    stats['vpip'] = (vpip_hands / total_hands * 100) if total_hands > 0 else 0
    
    # Calculate PFR (Pre-Flop Raise)
    pfr_hands = 0
    for hand_num, hand_data in hands.items():
        preflop_actions = hand_data['betting_rounds']['pre-flop']['actions']
        raise_actions = [a for a in preflop_actions if a['action'] == 'raise']
        if raise_actions:
            pfr_hands += 1
    
    stats['pfr'] = (pfr_hands / total_hands * 100) if total_hands > 0 else 0
    
    # Calculate Aggression Frequency
    total_aggressive_actions = stats['total_raises'] + stats['total_bets']
    total_passive_actions = stats['total_calls'] + stats['total_checks']
    total_actions = total_aggressive_actions + total_passive_actions
    
    stats['aggression_frequency'] = (total_aggressive_actions / total_actions * 100) if total_actions > 0 else 0
    
    # Calculate Aggression Factor
    stats['aggression_factor'] = (total_aggressive_actions / stats['total_calls']) if stats['total_calls'] > 0 else 0
    
    # Calculate win rate
    stats['win_rate'] = (stats['hands_won'] / total_hands * 100) if total_hands > 0 else 0
    
    # Calculate average pot
    total_pot_investment = sum(hand_data['investment'] for hand_data in hands.values())
    stats['average_pot'] = total_pot_investment / total_hands if total_hands > 0 else 0
    
    # Calculate positional stats
    for position in ['early', 'middle', 'late']:
        pos_stats = player_data['positional_stats'][position]
        pos_hands = pos_stats['hands']
        if pos_hands > 0:
            # Calculate VPIP and PFR by position
            pos_vpip_hands = 0
            pos_pfr_hands = 0
            
            for hand_num, hand_data in hands.items():
                if hand_data.get('position') == position:
                    preflop_actions = hand_data['betting_rounds']['pre-flop']['actions']
                    voluntary_actions = [a for a in preflop_actions if a['action'] in ['call', 'raise']]
                    raise_actions = [a for a in preflop_actions if a['action'] == 'raise']
                    
                    if voluntary_actions:
                        pos_vpip_hands += 1
                    if raise_actions:
                        pos_pfr_hands += 1
            
            pos_stats['vpip'] = (pos_vpip_hands / pos_hands * 100) if pos_hands > 0 else 0
            pos_stats['pfr'] = (pos_pfr_hands / pos_hands * 100) if pos_hands > 0 else 0
    
    return player_data

def generate_playing_style(player_data):
    """Generate playing style based on statistics"""
    stats = player_data['stats']
    
    vpip = stats['vpip']
    pfr = stats['pfr']
    aggression = stats['aggression_frequency']
    
    # Determine tightness (VPIP-based)
    if vpip < 15:
        tightness = "Ultra-Tight"
    elif vpip < 25:
        tightness = "Tight"
    elif vpip < 35:
        tightness = "Moderate"
    else:
        tightness = "Loose"
    
    # Determine aggression (PFR and aggression frequency based)
    if aggression > 60:
        aggression_level = "Hyper-Aggressive"
    elif aggression > 45:
        aggression_level = "Aggressive"
    elif aggression > 30:
        aggression_level = "Moderate"
    else:
        aggression_level = "Passive"
    
    # Determine player type based on VPIP/PFR gap
    vpip_pfr_gap = vpip - pfr
    if vpip_pfr_gap > 15:
        player_type = "Calling Station"
    elif vpip_pfr_gap > 8:
        player_type = "Loose-Passive"
    elif pfr > vpip * 0.8:
        player_type = "Lag (Loose-Aggressive)"
    elif pfr > vpip * 0.6:
        player_type = "Tag (Tight-Aggressive)"
    else:
        player_type = "Rock"
    
    style = f"{tightness} {aggression_level}"
    
    # Risk score calculation (0-100)
    risk_factors = [
        min(vpip / 40 * 25, 25),  # VPIP contribution (max 25)
        min(aggression / 60 * 25, 25),  # Aggression contribution (max 25)
        min((stats['preflop_raise'] / stats['hands_played'] * 100) / 20 * 25, 25),  # Pre-flop raise frequency
        min((stats['total_raises'] / (stats['total_calls'] + 1)) * 25, 25)  # Raise/Call ratio
    ]
    
    risk_score = min(sum(risk_factors), 100)
    
    return style, player_type, risk_score

def generate_player_reports(game_code):
    """Generate comprehensive analysis reports for all players"""
    if game_code not in game_data:
        return {}
    
    reports = {}
    
    for player_name, player_data in game_data[game_code].items():
        # Calculate statistics
        player_data = calculate_player_statistics(player_data, player_name)
        
        # Generate playing style
        style, player_type, risk_score = generate_playing_style(player_data)
        player_data['style'] = style
        player_data['risk_score'] = risk_score
        
        # Generate AI summary
        stats = player_data['stats']
        summary = f"""
Player: {player_name}
Playing Style: {style} ({player_type})
Risk Score: {risk_score:.1f}/100

Key Statistics:
- VPIP: {stats['vpip']:.1f}% (Voluntarily Put $ In Pot)
- PFR: {stats['pfr']:.1f}% (Pre-Flop Raise)
- Aggression Frequency: {stats['aggression_frequency']:.1f}%
- Aggression Factor: {stats['aggression_factor']:.1f}
- Hands Played: {stats['hands_played']}
- Win Rate: {stats['win_rate']:.1f}%
- Total Profit: ${player_data['total_profit']:.2f}
- Total Buy-ins: ${player_data.get('total_buy_ins', 0):.2f}

Positional Analysis:
- Early Position: VPIP {player_data['positional_stats']['early']['vpip']:.1f}%, PFR {player_data['positional_stats']['early']['pfr']:.1f}%
- Middle Position: VPIP {player_data['positional_stats']['middle']['vpip']:.1f}%, PFR {player_data['positional_stats']['middle']['pfr']:.1f}%
- Late Position: VPIP {player_data['positional_stats']['late']['vpip']:.1f}%, PFR {player_data['positional_stats']['late']['pfr']:.1f}%

Action Distribution:
- Raises: {stats['total_raises']}
- Calls: {stats['total_calls']}
- Checks: {stats['total_checks']}
- Folds: {stats['total_folds']}

Notable Achievements:
- Biggest Pot Won: ${stats['biggest_pot_won']:.2f}
- Biggest Pot Lost: ${stats['biggest_pot_lost']:.2f}
- Average Pot: ${stats['average_pot']:.2f}
"""
        
        player_data['ai_summary'] = summary
        reports[player_name] = {
            'style': style,
            'player_type': player_type,
            'risk_score': risk_score,
            'summary': summary,
            'stats': stats,
            'positional_stats': player_data['positional_stats'],
            'total_profit': player_data['total_profit'],
            'total_buy_ins': player_data.get('total_buy_ins', 0)
        }
    
    return reports

@app.route('/analysis/<code>')
def show_analysis(code):
    """Route to display player analysis reports"""
    if code not in game_data:
        return "Game data not found", 404
    
    reports = generate_player_reports(code)
    return render_template('analysis.html', reports=reports, game_code=code)

@app.route('/download_report/<game_code>/<player_name>')
def download_report(game_code, player_name):
    """Route to download player analysis report"""
    if game_code not in game_data or player_name not in game_data[game_code]:
        return "Report not found", 404
    
    player_data = game_data[game_code][player_name]
    summary = player_data.get('ai_summary', 'No analysis available')
    
    # Create a response with the file
    from flask import make_response
    response = make_response(summary)
    response.headers["Content-Disposition"] = f"attachment; filename={player_name}_analysis.txt"
    response.headers["Content-type"] = "text/plain"
    return response

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
