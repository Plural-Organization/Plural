from rich.text import Text
from textual.widgets import RichLog, Static

from plural.client.presenter import Line


class Transcript(RichLog):
    def __init__(self) -> None:
        super().__init__(wrap=True, markup=False, highlight=False, id="transcript")

    def add(self, line: Line) -> None:
        self.write(Text(line.text, style=line.style))


class LiveReply(Static):
    def show(self, text: str) -> None:
        self.update(Text(text[-2000:], style="italic"))
        self.display = bool(text)
