"""
Standalone interpreter of the BYC script that runs it in a sandbox and stores
game states.
"""

from base64 import urlsafe_b64encode
import logging
from pathlib import Path
import re
from urllib.parse import quote
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.expected_conditions import \
    visibility_of_element_located, invisibility_of_element
from selenium.webdriver.support.wait import WebDriverWait

class Dialog:
    """
    Parser for HTML dialogs made by the BYC script.
    """

    BUTTON_ATTRIBUTES = ("class", "innerText")

    def __init__(self, dialog):
        # TODO: Parse HTML within elements to display colors and so on?
        # Reuse the Cards object?
        self.element = dialog
        self.msg = dialog.find_element_by_class_name("msg").get_attribute("innerHTML").replace("<br>", "\n")
        self.buttons = []
        try:
            self.input = dialog.find_element_by_css_selector("input[type=text]")
        except NoSuchElementException:
            self.input = False
        self.options = {}

        buttons = dialog.find_elements_by_tag_name("button")
        for index, button in enumerate(buttons):
            self.buttons.append(button.get_attribute("innerText"))
            for attribute in self.BUTTON_ATTRIBUTES:
                self.options[button.get_attribute(attribute)] = index

    # TODO: Language changes (BYC, Discord, CMD)
    # press Cancel      | use !cancel                         | enter "cancel"
    # quote this post   | talk to the bot in #byc-GAMEID-USER | ???

class ByYourCommand:
    """
    By Your Command game.
    """

    SCRIPT_PATH = Path("byc.js")
    STYLE_PATH = Path("game_state.css")

    def __init__(self, game_id, script_url):
        self.driver = None
        self.game_id = game_id
        self.script_url = script_url
        self.load()

    def __del__(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def load(self):
        """
        Load the script, web driver and other parsers for the BYC game.
        """

        # Load script
        if not self.SCRIPT_PATH.exists():
            script = self._load_script()
            with self.SCRIPT_PATH.open('w') as script_file:
                script_file.write(script)

        # Setup Selenium web driver
        self._load_driver()

    def _load_driver(self):
        # Create the Selenium web driver (no screen necesarry, file access)
        options = Options()
        options.headless = True
        options.add_argument("allow-file-access-from-files")
        self.driver = webdriver.Chrome(chrome_options=options)

    def run_page(self, user, choices, game_state):
        """
        Perform action(s) for a user through script dialogs to bring the game
        to a certain state.
        """

        # TODO: Think about how to handle cross-play and "undos" that the group 
        # wants to do
        # TODO: Do we need to satisfy the script with a Quoted Article and thus 
        # an article ID?

        try:
            current_user = self.driver.find_element_by_tag_name("h1")
            if current_user.get_attribute("innerText") != user:
                raise ValueError("Context switched")

            choices = choices[-1:]
        except (NoSuchElementException, ValueError):
            page = f"game/page-{self.game_id}-{urlsafe_b64encode(user.encode()).decode()}.html"
            page_path = Path(page)
            script_url = self.SCRIPT_PATH.resolve().as_uri()
            with page_path.open('w') as page_file:
                # TODO: Include current game state BBCode in textarea
                page_file.write(f'''<!DOCTYPE html>
                <html>
                    <head><title>BYC</title></head>
                    <body>
                        <h1>{user}</h1>
                        <a href="/collection/user/{user}">Collection</a>
                        <textarea>{game_state}</textarea>
                        <script src="{script_url}"></script>
                    </body>
                </html>''')

            self.driver.get(page_path.resolve().as_uri())

        try:
            dialog = Dialog(self._wait_for_dialog())
        except TimeoutException:
            return self._get_game_state(user)

        for choice in choices:
            logging.info("Handling choice: %s", choice)
            if dialog.input and not isinstance(choice, int):
                dialog.input.send_keys(choice)
                button = dialog.element.find_element_by_class_name("ok")
            else:
                selector = f"button:nth-child({choice})"
                button = dialog.element.find_element_by_css_selector(selector)

            logging.info("Pressed: %s", button.get_attribute("innerText"))
            button.click()

            try:
                wait = invisibility_of_element(dialog.element)
                self._wait_for_dialog(wait=wait)
            except TimeoutException:
                raise RuntimeError("Dialog did not disappear")

            try:
                dialog = Dialog(self._wait_for_dialog())
            except TimeoutException:
                return self._get_game_state(user)

        logging.info("Dialog: %s", dialog.element.get_attribute("innerHTML"))
        logging.info("Browser log: %r", self.driver.get_log("browser"))
        return dialog

    def _get_game_state(self, user):
        textarea = self.driver.find_element_by_tag_name("textarea")
        return f'[q="{user}"]{textarea.get_attribute("value")}[/q]'

    def save_game_state_screenshot(self, html):
        """
        Using HTML parsed from a BYC Game State quote, create a screenshot
        that displays the current game state.
        """

        page_path = Path(f"game/game-state-{self.game_id}.html")
        style_url = self.STYLE_PATH.resolve().as_uri()
        with page_path.open('w') as page_file:
            page_file.write(f'''<!DOCTYPE html>
            <html>
                <head>
                    <title>BYC: Game State</title>
                    <link rel="stylesheet" type="text/css" href="{style_url}">
                </head>
                <body>{html}</body>
            </html>''')

        # TODO: Adjust window size to fit
        self.driver.get(page_path.resolve().as_uri())
        self.driver.save_screenshot(f"game/game-state-{self.game_id}.png")

    def _wait_for_dialog(self, wait=None):
        if wait is None:
            wait = visibility_of_element_located((By.CLASS_NAME, "dialog"))
        return WebDriverWait(self.driver, 2).until(wait)

    def _load_script(self):
        # Regular expressions that put together the source code from the page.
        qre = []
        for tag in ["A", "B", "C", "D", "E", "F"]:
            qre.append(re.compile(fr"STARTBYC{tag}(?:(?!(STARTBYC|ENDBYC)).)*ENDBYC{tag}"))

        response = requests.get(self.script_url)
        response.raise_for_status()

        src = response.text
        totaljs = ""
        startchar = 9
        endchar = -7
        for part in qre:
            match = part.search(src)
            if not match:
                raise RuntimeError("Could not read script.")
            totaljs += match.group(0)[startchar:endchar]

        return totaljs.replace("&gt;", ">").replace("&amp;", "&")
