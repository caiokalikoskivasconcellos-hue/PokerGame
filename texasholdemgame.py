from deck import Deck
from collections import Counter
from player import Player
from card import Card

class TexasHoldemGame:
    end_game = False  # class variable shared by all instances

    def __init__(self, players):
        self.players = players
        self.deck = Deck()
        self.community_cards = []
        self.current_highest_bet = 0
        self.pots = []

    def deal_hole_cards(self):
        # deal 2 hole cards to each player
        for _ in range(2):
            for player in self.players:
                player.receive_card(self.deck.deal_card())

        # show hole cards to each player
        for player in self.players:
            answer = input(f"{player.name}, I will display your hole cards for 5 seconds. Confirm you read this message (y/n): ").strip().lower()
            if answer.startswith('y'):
                print(f"{player.name} has the following hole cards: {player.holecards}")
                #time.sleep(5)
                #print("\033[F\033[K" * 2)

    def deal_flop(self):
        self.community_cards.extend([self.deck.deal_card() for _ in range(3)])

    def deal_turn(self):
        self.community_cards.append(self.deck.deal_card())

    def deal_river(self):
        self.community_cards.append(self.deck.deal_card())
    
    def create_pots(self):
        self.pots = []  # reset pots list

        # Keep going until all remaining bets are zero
        while True:
            # Get all players who still have money in the pot and are eligible
            active_players = [p for p in self.players if p.currentbet > 0 and (not p.is_out() or p.has_gone_all_in)]
            if not active_players:
                break

            # Find minimum contribution among active players
            min_contribution = min(p.currentbet for p in active_players)

            # Players who are contributing at least min_contribution
            pot_players = [p for p in active_players if p.currentbet >= min_contribution]

            # Calculate pot amount
            pot_amount = min_contribution * len(pot_players)

            # Subtract that amount from each contributing player
            for p in pot_players:
                p.currentbet -= min_contribution

            # Save pot info
            self.pots.append({
                "amount": pot_amount,
                "players": pot_players.copy()  # snapshot of contributors
            })

    
    def betting_round(self):
        round_active = True
        lma = 0
        while round_active and (Player.players_folded < len(self.players)-1) and (Player.players_all_in < (len(self.players)-1)):
            round_active = False
            raise_occurred = False
            for player in self.players:
                if player.hasfolded or player.has_gone_all_in or player.is_out():
                    continue
                done = False
                if lma == player.number:
                    round_active = False
                    break
                while not done:
                    action = input(f"\n{player.name}, choose an action (fold, check, call, raise): ").lower()
                    done = True
                    if action == "fold":
                        player.fold()
                        if player.number == len(self.players) and raise_occurred:
                            round_active = True
                    elif action == "check":
                        if not player.check(self.current_highest_bet):
                            done = False
                        else:
                            round_active = False
                        if player.number == len(self.players) and raise_occurred:
                            round_active = True
                    elif action == "call":
                        if player.call(self.current_highest_bet):
                            round_active = False
                        else:
                            done = False
                        if player.number == len(self.players) and raise_occurred:
                            round_active = True
                    elif action == "raise":
                        try:
                            raise_amount = float(input("Enter raise amount: "))
                        except ValueError:
                            print("Invalid number. Try again.")
                            done = False
                            continue
                        if player.raise_bet(raise_amount, self.current_highest_bet):
                            self.current_highest_bet += raise_amount
                            round_active = True
                            lma = player.number
                        else:
                            done = False
                        if player.number != 1 and len(self.players) > player.number:
                            raise_occurred = True
                        if player.number == len(self.players) and raise_occurred:
                            round_active = True
                    else:
                        print("Invalid action. Try again.")
                        done = False
    
    def calc_hand(self, community_cards, hole_cards):
        return_list = []
        self.s = False
        self.hc = True
        all_cards = community_cards + hole_cards
        all_cards.sort(key=lambda card: card.rank)
        rank_counts = Counter(card.rank for card in all_cards)
        suit_counts = Counter(card.suit for card in all_cards)
        self.fk = 4 in rank_counts.values()
        self.fh = 3 in rank_counts.values() and 2 in rank_counts.values()
        self.f = any(count >= 5 for count in suit_counts.values())
        flush_suit = next((suit for suit, count in suit_counts.items() if count >= 5), None)
        self.tk = 3 in rank_counts.values()
        self.tp = list(rank_counts.values()).count(2) >= 2
        self.p = 2 in rank_counts.values()
        suits = {}
        royal_ranks = {10, 11, 12, 13, 14}
        for card in all_cards:
            suits.setdefault(card.suit, []).append(card)
        self.rf = False
        for suited_cards in suits.values():
            suited_ranks = set(card.rank for card in suited_cards)
            if royal_ranks.issubset(suited_ranks):
                self.rf = True
                break
        count = 1
        duplicates = 0
        self.sf = False
        for i in range(len(all_cards)-1, 0, -1):
            if count == 5:
                self.s = True
                sstart = i
                break
            if all_cards[i-1].rank - all_cards[i].rank == -1:
                count += 1
            else:
                if all_cards[i-1].rank - all_cards[i].rank != 0:
                    count = 1
                else:
                    duplicates += 1
        if self.s:
            flush_count = Counter(card.suit for card in all_cards[sstart:sstart + 5 + duplicates])
            if 5 in flush_count.values():
                self.sf = True
        
        if self.rf:
            return_list.append(10)
            return_list.append(10+11+12+13+14)
            return_list.append(0)
            return return_list
        elif self.sf:
            return_list.append(9)
            return_list.append(all_cards[sstart + 4].rank)
            return return_list
        elif self.fk:
            return_list.append(8)
            fk_rank = next((rank for rank, count in rank_counts.items() if count == 4), None)
            kicker = max(card.rank for card in all_cards if card.rank != fk_rank)
            return_list.append(fk_rank)
            return_list.append(kicker)
            return return_list
        elif self.fh:
            return_list.append(7)
            return_list.append(next((rank for rank, count in rank_counts.items() if count == 3), None))
            return_list.append(max((rank for rank, count in rank_counts.items() if count == 2), default=None))
            return return_list
        elif self.f:
            return_list.append(6)
            flush_cards = [card for card in all_cards if card.suit == flush_suit]
            flush_cards_sorted = sorted(flush_cards, key=lambda c: c.rank, reverse=True)
            return_list.append(flush_cards_sorted[0].rank)
            return_list.append(flush_cards_sorted[1].rank)
            return_list.append(flush_cards_sorted[2].rank)
            return_list.append(flush_cards_sorted[3].rank)
            return_list.append(flush_cards_sorted[4].rank)
            return return_list
        elif self.s:
            return_list.append(5)
            return_list.append(all_cards[sstart + 4].rank)
            return return_list
        elif self.tk:
            return_list.append(4)
            trip_rank = max((rank for rank, count in rank_counts.items() if count == 3), default=None)
            return_list.append(trip_rank)
            kickers = [card.rank for card in all_cards if card.rank != trip_rank]
            kickers = sorted(set(kickers), reverse=True)[:2]
            return_list.extend(kickers)
            return return_list
        elif self.tp:
            pairs = sorted((rank for rank, count in rank_counts.items() if count == 2), reverse=True)
            pair_rank1, pair_rank2 = pairs[:2]
            kicker = max(card.rank for card in all_cards if card.rank != pair_rank1 and card.rank != pair_rank2)
            return_list.append(3)
            return_list.append(pair_rank1)
            return_list.append(pair_rank2)
            return_list.append(kicker)
            return return_list
        elif self.p:
            return_list.append(2)
            pair_rank = max((rank for rank, count in rank_counts.items() if count == 2), default=None)
            return_list.append(pair_rank)
            kickers = [card.rank for card in all_cards if card.rank != pair_rank]
            kickers = sorted(set(kickers), reverse=True)[:3]
            return_list.extend(kickers)
            return return_list
        elif self.hc:
            return_list.append(1)
            return_list.append(all_cards[-1].rank)
            return_list.append(all_cards[-2].rank)
            return_list.append(all_cards[-3].rank)
            return_list.append(all_cards[-4].rank)
            return_list.append(all_cards[-5].rank)
            return return_list
    
    def play_game(self):
        # Reset each player
        for player in self.players:
            player.reset_all()

        self.community_cards = []
        self.pots = []
        self.current_highest_bet = 0
        self.deck = Deck()

        self.deck.shuffle()
        self.deal_hole_cards()
        print("Hole cards dealt.")

        print("\nStarting betting round:")
        self.betting_round()

        print("\nDealing the flop:")
        self.deal_flop()
        print("Community cards:", self.community_cards)

        print("\nStarting betting round:")
        self.betting_round()

        print("\nDealing the turn:")
        self.deal_turn()
        print("Community cards:", self.community_cards)

        print("\nStarting betting round:")
        self.betting_round()

        print("\nDealing the river:")
        self.deal_river()
        print("Community cards:", self.community_cards)

        print("\nFinal betting round:")
        self.betting_round()
        print("\nCommunity cards:", self.community_cards)
        
        # Update pot
        self.create_pots()
        print("Pots are:")
        for i, pot in enumerate(self.pots):
            player_names = [player.name for player in pot["players"] if not player.hasfolded]
            print(f"Pot {i}: ${pot['amount']} between {', '.join(player_names)}")

        for pot in self.pots:
            for player in pot["players"]:
                if player.hasfolded:
                    continue
                player.get_hand(self.community_cards, self)
            winners = []
            winnerhand = []
            winnerscore = -1
            for player in pot["players"]:
                if player.hasfolded:
                    continue
                if player.handscores[0] > winnerscore:
                    winners = [player]
                    winnerhand = player.handscores
                    winnerscore = player.handscores[0]
                elif player.handscores[0] == winnerscore:    
                    for i in range(len(winnerhand)):
                        if player.handscores[i] > winnerhand[i]:
                            winners = [player]
                            winnerhand = player.handscores
                            winnerscore = player.handscores[0]
                            break
                        elif player.handscores[i] < winnerhand[i]:
                            break
                    else:
                        winners.append(player)
            print(f"Congrats to {', '.join((player.name for player in winners))} for winning this pot")
            for player in winners:
                player.money += (pot["amount"] / len(winners))
    
    def to_dict(self):
        return {
            "players": [player.to_dict() for player in self.players],
            "deck": self.deck.to_dict(),
            "community_cards": [card.to_dict() for card in self.community_cards],
            "current_highest_bet": self.current_highest_bet,
            "pots": [
                {
                    "amount": pot["amount"],
                    # Store player IDs or numbers, not whole player objects, for reference
                    "players": [p.number for p in pot["players"]]
                }
                for pot in self.pots
            ]
        }

    @classmethod
    def from_dict(cls, data):
        # Recreate players
        players = [Player.from_dict(pdata) for pdata in data["players"]]

        # Recreate deck
        deck = Deck.from_dict(data["deck"])

        # Recreate community cards
        community_cards = [Card.from_dict(cdata) for cdata in data["community_cards"]]

        # Initialize a new game with players
        game = cls(players)
        game.deck = deck
        game.community_cards = community_cards
        game.current_highest_bet = data["current_highest_bet"]

        # Rebuild pots, mapping player numbers back to player instances
        game.pots = []
        for pot_data in data["pots"]:
            pot_players = [p for p in players if p.number in pot_data["players"]]
            game.pots.append({
                "amount": pot_data["amount"],
                "players": pot_players
            })

        return game