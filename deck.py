import random
from card import Card, SUITS, RANKS

class Deck:
    def __init__(self):
        self.cards = [Card(suit, rank) for suit in SUITS for rank in RANKS]
        random.shuffle(self.cards)

    def deal_card(self):
        if not self.cards:
            return None
        return self.cards.pop()
    def shuffle(self):
        random.shuffle(self.cards)
    def to_dict(self):
        # serialize each card
        return [card.to_dict() for card in self.cards]

    @classmethod
    def from_dict(cls, data):
        # data is a list of card dicts
        cards = [Card.from_dict(cd) for cd in data]
        return cls(cards)