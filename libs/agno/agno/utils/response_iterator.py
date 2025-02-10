class ResponseIterator:
    def __init__(self):
        self.items = []
        self.index = 0

    def add(self, item):
        self.items.append(item)

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.items):
            raise StopIteration
        item = self.items[self.index]
        self.index += 1
        return item
