SUITS = {1: "clubs", 2: "diamonds", 3: "hearts", 4: "spades"}
RANKS = {
    2: "02", 3: "03", 4: "04", 5: "05", 6: "06", 7: "07",
    8: "08", 9: "09", 10: "10", 11: "jack", 12: "queen", 13: "king", 14: "ace"
}

class Card:
    def __init__(self, suit: int, rank: int):
        self.suit = suit
        self.rank = rank
        self.visible = False
    
    def __str__(self):
        return f"{RANKS[self.rank]} of {SUITS[self.suit]}"

    def __repr__(self):
        return self.__str__()

    def get_image_filename(self):
        if self.visible:
            suit_name = SUITS[self.suit]
            rank_name = RANKS[self.rank]
            return f"{suit_name}_{rank_name}.png"
        else:
            return "back01.png"

    def to_dict(self):
        return {
            "suit": self.suit,
            "rank": self.rank,
            "visible": self.visible,
            "image_filename": self.get_image_filename()
        }

    @classmethod
    def from_dict(cls, data):
        card = cls(data["suit"], data["rank"])
        card.visible = data.get("visible", False)
        return card
