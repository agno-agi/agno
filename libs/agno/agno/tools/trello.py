import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from trello import TrelloClient  # type: ignore
except ImportError:
    raise ImportError("`py-trello` not installed.")


class TrelloTools(Toolkit):
    """Trello board and card management toolkit.

    Requires py-trello: `pip install py-trello`

    Authentication:
        Set environment variables TRELLO_API_KEY, TRELLO_API_SECRET, and TRELLO_TOKEN,
        or pass them as constructor arguments.

        Get credentials at: https://trello.com/app-key

    Args:
        api_key: Trello API key. Falls back to TRELLO_API_KEY env var.
        api_secret: Trello API secret. Falls back to TRELLO_API_SECRET env var.
        token: Trello token. Falls back to TRELLO_TOKEN env var.
        list_boards: Enable list_boards tool. Defaults to True.
        get_board_lists: Enable get_board_lists tool. Defaults to True.
        get_cards: Enable get_cards tool. Defaults to True.
        create_card: Enable create_card tool. Defaults to False (creates external content).
        create_board: Enable create_board tool. Defaults to False (creates external content).
        create_list: Enable create_list tool. Defaults to False (creates external content).
        move_card: Enable move_card tool. Defaults to False (modifies external content).
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        token: Optional[str] = None,
        list_boards: bool = True,
        get_board_lists: bool = True,
        get_cards: bool = True,
        create_card: bool = False,
        create_board: bool = False,
        create_list: bool = False,
        move_card: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("TRELLO_API_KEY")
        self.api_secret = api_secret or getenv("TRELLO_API_SECRET")
        self.token = token or getenv("TRELLO_TOKEN")

        if not (self.api_key and self.api_secret and self.token):
            logger.warning("Missing Trello credentials")

        try:
            self.client = TrelloClient(api_key=self.api_key, api_secret=self.api_secret, token=self.token)
        except Exception:
            logger.exception("Error initializing Trello client")
            self.client = None

        tools: List[Callable] = []
        if all or list_boards:
            tools.append(self.list_boards)
        if all or get_board_lists:
            tools.append(self.get_board_lists)
        if all or get_cards:
            tools.append(self.get_cards)
        if all or create_card:
            tools.append(self.create_card)
        if all or create_board:
            tools.append(self.create_board)
        if all or create_list:
            tools.append(self.create_list)
        if all or move_card:
            tools.append(self.move_card)

        super().__init__(name="trello", tools=tools, **kwargs)

    def create_card(self, board_id: str, list_name: str, card_title: str, description: str = "") -> str:
        """
        Create a new card in the specified board and list.

        Args:
            board_id (str): ID of the board to create the card in
            list_name (str): Name of the list to add the card to
            card_title (str): Title of the card
            description (str): Description of the card

        Returns:
            str: JSON string containing card details or error message
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_info(f"Creating card {card_title}")

            board = self.client.get_board(board_id)
            target_list = None

            for lst in board.list_lists():
                if lst.name.lower() == list_name.lower():
                    target_list = lst
                    break

            if not target_list:
                return json.dumps({"error": f"List '{list_name}' not found on board"})

            card = target_list.add_card(name=card_title, desc=description)

            return json.dumps({"id": card.id, "name": card.name, "url": card.url, "list": list_name})

        except Exception as e:
            return json.dumps({"error": f"Error creating card: {e}"})

    def get_board_lists(self, board_id: str) -> str:
        """
        Get all lists on a board.

        Args:
            board_id (str): ID of the board

        Returns:
            str: JSON string containing lists information
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_debug(f"Getting lists for board {board_id}")

            board = self.client.get_board(board_id)
            lists = board.list_lists()

            lists_info = [{"id": lst.id, "name": lst.name, "cards_count": len(lst.list_cards())} for lst in lists]

            return json.dumps({"lists": lists_info})

        except Exception as e:
            return json.dumps({"error": f"Error getting board lists: {e}"})

    def move_card(self, card_id: str, list_id: str) -> str:
        """
        Move a card to a different list.

        Args:
            card_id (str): ID of the card to move
            list_id (str): ID of the destination list

        Returns:
            str: JSON string containing result of the operation
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_debug(f"Moving card {card_id} to list {list_id}")

            card = self.client.get_card(card_id)
            card.change_list(list_id)

            return json.dumps({"success": True, "card_id": card_id, "new_list_id": list_id})

        except Exception as e:
            return json.dumps({"error": f"Error moving card: {e}"})

    def get_cards(self, list_id: str) -> str:
        """
        Get all cards in a list.

        Args:
            list_id (str): ID of the list

        Returns:
            str: JSON string containing cards information
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_debug(f"Getting cards for list {list_id}")

            trello_list = self.client.get_list(list_id)
            cards = trello_list.list_cards()

            cards_info = [
                {
                    "id": card.id,
                    "name": card.name,
                    "description": card.description,
                    "url": card.url,
                    "labels": [label.name for label in card.labels],
                }
                for card in cards
            ]

            return json.dumps({"cards": cards_info})

        except Exception as e:
            return json.dumps({"error": f"Error getting cards: {e}"})

    def create_board(self, name: str, default_lists: bool = False) -> str:
        """
        Create a new Trello board.

        Args:
            name (str): Name of the board
            default_lists (bool): Whether the default lists should be created

        Returns:
            str: JSON string containing board details or error message
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_info(f"Creating board {name}")

            board = self.client.add_board(board_name=name, default_lists=default_lists)

            return json.dumps(
                {
                    "id": board.id,
                    "name": board.name,
                    "url": board.url,
                }
            )

        except Exception as e:
            return json.dumps({"error": f"Error creating board: {e}"})

    def create_list(self, board_id: str, list_name: str, pos: str = "bottom") -> str:
        """
        Create a new list on a specified board.

        Args:
            board_id (str): ID of the board to create the list in
            list_name (str): Name of the new list
            pos (str): Position of the list - 'top', 'bottom', or a positive number

        Returns:
            str: JSON string containing list details or error message
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_info(f"Creating list {list_name}")

            board = self.client.get_board(board_id)
            new_list = board.add_list(name=list_name, pos=pos)

            return json.dumps(
                {
                    "id": new_list.id,
                    "name": new_list.name,
                    "pos": new_list.pos,
                    "board_id": board_id,
                }
            )

        except Exception as e:
            return json.dumps({"error": f"Error creating list: {e}"})

    def list_boards(self, board_filter: str = "all") -> str:
        """
        Get a list of all boards for the authenticated user.

        Args:
            board_filter (str): Filter for boards. Options: 'all', 'open', 'closed',
                              'organization', 'public', 'starred'. Defaults to 'all'.

        Returns:
            str: JSON string containing list of boards
        """
        try:
            if not self.client:
                return json.dumps({"error": "Trello client not initialized"})

            log_debug(f"Listing boards with filter: {board_filter}")

            boards = self.client.list_boards(board_filter=board_filter)

            boards_list = []
            for board in boards:
                board_data = {
                    "id": board.id,
                    "name": board.name,
                    "description": getattr(board, "description", ""),
                    "url": board.url,
                    "closed": board.closed,
                    "starred": getattr(board, "starred", False),
                    "organization": getattr(board, "idOrganization", None),
                }
                boards_list.append(board_data)

            return json.dumps(
                {
                    "filter_used": board_filter,
                    "total_boards": len(boards_list),
                    "boards": boards_list,
                }
            )

        except Exception as e:
            return json.dumps({"error": f"Error listing boards: {e}"})
