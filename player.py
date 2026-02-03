from card import Card
class Player:
    moneychipsratio: float
    number_of_players = 0
    players_folded = 0
    players_all_in = 0
    def __init__(self, name: str, money, number: int, id: str, avatar=None, ready=False):
        self.name = name
        self.money = money
        self.number = number
        self.currentbet = 0
        self.hasfolded = False
        self.has_gone_all_in = False
        self.holecards = []
        Player.number_of_players += 1
        self.handscores = []
        self.id = id
        self.ready = ready
        self.avatar = avatar
        self.last_action = ''
        self.moved = False
        self.isout = False
        self.dealer = False
        self.BB = False
        self.SB = False

    def receive_card(self, card: Card):
        self.holecards.append(card)
    def reset_all(self):
        self.holecards.clear()
        self.currentbet = 0
        self.hasfolded = False
        self.handscores = []

    def end_game(self):
        print(f"{self.name} has decided to stop playing and exit the game!")
        print(f"They left with a balance of ${self.money} and wishes all remaining players good luck!")

    def fold(self):
        self.hasfolded = True
        Player.players_folded += 1
        print(f"{self.name} folds.")

    def check(self, current_highest_bet):
        if self.currentbet == current_highest_bet:
            print(f"{self.name} checks.")
            return True
        print(f"{self.name} cannot check; needs to call or raise.")
        return False

    def call(self, current_highest_bet):
        amount_to_call = current_highest_bet - self.currentbet
        if self.money >= amount_to_call:
            self.money -= amount_to_call
            self.currentbet += amount_to_call
            print(f"{self.name} calls with {amount_to_call}")
            if self.money == 0:
                self.has_gone_all_in = True
                Player.players_all_in += 1
            return True
        else:
            action = input(f"/n{self.name} cannot call; insufficient funds. Would you like to go all in instead?").strip().lower()
            if action.startswith("y"):
                amount_to_call = self.money - self.currentbet
                self.money -= amount_to_call
                self.currentbet += amount_to_call
                self.has_gone_all_in = True
                Player.players_all_in += 1
                return True
            else:
                return False

    def raise_bet(self, amount, current_highest_bet):
        total_bet = current_highest_bet + amount
        amount_to_raise = total_bet - self.currentbet
        if self.money >= amount_to_raise:
            self.money -= amount_to_raise
            self.currentbet += amount_to_raise
            print(f"{self.name} raises to {total_bet}")
            if self.money == 0:
                self.has_gone_all_in = True
                Player.players_all_in += 1
            return True
        else:
            print(f"{self.name} cannot raise; insufficient funds.")
            return False

    def is_out(self):
        self.isout = self.money == 0
        return self.money == 0
    
    def hand_name(self, hand_score: int):
        if hand_score == 10:
            return "Royal Flush"
        elif hand_score == 9:
            return "Straight Flush"
        elif hand_score == 8:
            return "Four of a Kind"
        elif hand_score == 7:
            return "Full House"
        elif hand_score == 6:
            return "Flush"
        elif hand_score == 5:
            return "Straight"
        elif hand_score == 4:
            return "Three of a Kind"
        elif hand_score == 3:
            return "Two Pair"
        elif hand_score == 2:
            return "Pair"
        else:
            return "High Card"
    def get_hand(self, community_cards, holdem_game):
        self.handscores = holdem_game.calc_hand(community_cards, self.holecards)
        print(self.hand_name(self.handscores[0]))
    
    def to_dict(self):
        return {
            "name": self.name,
            "money": self.money,
            "number": self.number,
            "avatar": self.avatar,
            "currentbet": self.currentbet,
            "has_folded": self.hasfolded,
            "has_gone_all_in": self.has_gone_all_in,
            "holecards": [card.to_dict() for card in self.holecards],
            "handscores": self.handscores,
            "id": self.id,
            "ready": self.ready,
            "last_action": self.last_action,
            "current_bet": self.currentbet,
            "moved": self.moved,
            "is_out": self.isout,
            "dealer": self.dealer,
            "BB": self.BB,
            "SB": self.SB
        }
    @classmethod
    def from_dict(cls, data):
        player = cls(data["name"], data["money"], data["number"], id = data.get("id"), avatar=data.get("avatar"), ready=data.get("ready", False))
        player.currentbet = data.get("currentbet", 0)
        player.hasfolded = data.get("has_folded", False)
        player.has_gone_all_in = data.get("has_gone_all_in", False)
        player.holecards = [Card.from_dict(cd) for cd in data.get("holecards", [])]
        player.handscores = data.get("handscores", [])
        player.last_action = data.get("last_action")
        player.currentbet = data.get("current_bet")
        player.moved = data.get("moved", False)
        player.isout = data.get("is_out", False)
        player.dealer = data.get("dealer", False)
        player.BB = data.get("BB", False)
        player.SB = data.get("SB", False)
        return player
