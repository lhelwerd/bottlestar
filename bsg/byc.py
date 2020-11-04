"""
Standalone interpreter of the BYC script that runs it in a sandbox and stores
game states.
"""

from base64 import b64encode, b64decode, urlsafe_b64encode, urlsafe_b64decode
import json
import logging
from pathlib import Path
import re
from markdownify import markdownify
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.expected_conditions import \
    visibility_of_element_located, invisibility_of_element
from selenium.webdriver.support.wait import WebDriverWait

ROLE_TEXT = {
    "character":
        (" chooses to play ", " returns as ", " pick a new character"),
    "title":
        (" is now the ", " the Mutineer.", " receives the Mutineer card "),
    "loyalty":
        (" reveals ", " becomes a Cylon.", " is a [color=red]Cylon[/color]!")
}

def unique_hash(user):
    """
    Convert a username to a unique hash in order to make it safe for filenames.
    """

    return urlsafe_b64encode(user.encode()).decode()

class Dialog:
    """
    Parser for HTML dialogs made by the BYC script.
    """

    EMPTY = "0:e30=:0"
    BUTTON_ATTRIBUTES = ("class", "innerText")
    MSG_TAGS = ['b', 'i', 'br', 'strong', 'em']

    def __init__(self, dialog):
        self.element = dialog

        msg = dialog.find_element_by_class_name("msg").get_attribute("innerHTML")
        self.msg = markdownify(msg, convert=self.MSG_TAGS).replace('****', '')

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

    def __repr__(self):
        options = urlsafe_b64encode(json.dumps(self.options).encode()).decode()
        return f"{len(self.buttons)}:{options}:{1 if self.input else 0}"

    @classmethod
    def decode_options(cls, options):
        return json.loads(urlsafe_b64decode(options.encode()).decode())

    # TODO: Language changes (BYC, Discord, CMD)
    # press Cancel    | use **!cancel**                       | enter "cancel"
    # quote this post | use **!byc** in their private channel | ???
    # BGG             | Discord                               | command line

class ByYourCommand:
    """
    By Your Command game.
    """

    SCRIPT_PATH = Path("byc.js")
    STYLE_PATH = Path("game_state.css")
    GAME_SEED_REGEX = re.compile(r"(?:\[c\])?\[size=(?:1|0)\]\[color=#(?:F4F4FF|FFFFFF)\]New seed: (\S+)\[/color\]\[/size](?:\[/c\])?")
    QUOTE_REGEX = re.compile(r'\[q="([^"]+)"\](.*)\[/q\]', re.S)

    def __init__(self, game_id, user, script_url):
        self.driver = None
        self.game_id = game_id
        self.user = user
        self.script_url = script_url
        self.load()

    def __del__(self):
        self.stop()

    def stop(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except:
                pass

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
        self.driver.set_window_size(600, 1600)

    def retrieve_game_state(self, force=False):
        try:
            current_user = self.driver.find_element_by_tag_name("h1")
            if force or current_user.get_attribute("innerText") != self.user:
                raise ValueError("Context switched (user)")

            textarea = self.driver.find_element_by_tag_name("textarea")
            return textarea.get_attribute("value")
        except NoSuchElementException:
            raise ValueError("Context switched (state)")

    def run_page(self, choices, game_state, force=False, quits=False,
                 quote=True, num=1):
        """
        Perform action(s) for a user through script dialogs to bring the game
        to a certain state.
        """

        # TODO: Think about how to handle cross-play and "undos" that the group 
        # wants to do - manually grab a backup for now or do a crosspost fix
        # TODO: Do we need to satisfy the script with a Quoted Article and thus 
        # an article ID?

        try:
            self.retrieve_game_state(force=force)
            choices = choices[-num:]
        except ValueError:
            page = f"game/page-{self.game_id}-{unique_hash(self.user)}.html"
            page_path = Path(page)
            script_url = self.SCRIPT_PATH.resolve().as_uri()
            with page_path.open('w') as page_file:
                page_file.write(f'''<!DOCTYPE html>
                <html>
                    <head><title>BYC</title></head>
                    <body>
                        <h1>{self.user}</h1>
                        <a href="/collection/user/{self.user}">Collection</a>
                        <textarea>{game_state}</textarea>
                        <script src="{script_url}"></script>
                    </body>
                </html>''')

            self.driver.get(page_path.resolve().as_uri())

        try:
            dialog = Dialog(self._wait_for_dialog())
        except TimeoutException:
            logging.debug("Browser log (initial timeout): %r",
                          self.driver.get_log("browser"))
            return self._get_game_state(quote=quote)

        # Check for BYC updates
        if self._check_script_update():
            try:
                dialog = Dialog(self._wait_for_dialog())
            except TimeoutException:
                logging.debug("Browser log (timeout after update): %r",
                              self.driver.get_log("browser"))
                return self._get_game_state(quote=quote)

        for index, choice in enumerate(choices):
            logging.info("Handling choice #%d: %s", index, choice.lstrip("\b"))
            if dialog.input and not choice.startswith("\b"): # Non-button input
                dialog.input.send_keys(choice)
                button = dialog.element.find_element_by_class_name("ok")
            else:
                index = choice.lstrip("\b")
                selector = f"button:nth-child({index})"
                button = dialog.element.find_element_by_css_selector(selector)

            logging.info("Pressed: %s", button.get_attribute("innerText"))
            button.click()

            try:
                wait = invisibility_of_element(dialog.element)
                self._wait_for_dialog(wait=wait)
            except TimeoutException:
                raise RuntimeError("Dialog did not disappear")

            if quits and index == len(choices) - 1:
                # Don't wait for dialog if we know this is supposed to
                # Save and Quit, so we don't need to wait for a new dialog
                logging.debug("Browser log (quitting): %r",
                              self.driver.get_log("browser"))
                return self._get_game_state(quote=quote)

            try:
                dialog = Dialog(self._wait_for_dialog())
            except TimeoutException:
                logging.debug("Browser log (ending timeout): %r",
                              self.driver.get_log("browser"))
                return self._get_game_state(quote=quote)

        logging.debug("Browser log: %r", self.driver.get_log("browser"))
        return dialog

    def _wait_for_dialog(self, wait=None):
        if wait is None:
            wait = visibility_of_element_located((By.CLASS_NAME, "dialog"))
        return WebDriverWait(self.driver, 2).until(wait)

    def _get_game_state(self, quote=True):
        textarea = self.driver.find_element_by_tag_name("textarea")
        value = textarea.get_attribute("value").encode("iso-8859-1").decode()
        if quote:
            return f'[q="{self.user}"]{value}[/q]'

        return value

    @classmethod
    def get_quote_author(cls, state):
        match = cls.QUOTE_REGEX.search(state)
        if match:
            return match.group(1), match.group(2)

        return None, state

    @classmethod
    def load_game_seed(cls, seed):
        return json.loads(b64decode(seed.replace("-", "")).decode())

    @classmethod
    def get_game_seed(cls, game_state):
        match = cls.GAME_SEED_REGEX.search(game_state)
        if match:
            return cls.load_game_seed(match.group(1))

        return {}

    def make_game_seed(self, state):
        return f"[c][size=1][color=#FFFFFF]New seed: {state}[/color][/size][/c]"

    def set_game_seed(self, game_state, seed):
        encoded = b64encode(json.dumps(seed).encode()).decode()
        state = "-".join(re.findall(r".{1,20}", encoded))
        new_seed = self.make_game_seed(state)
        return self.GAME_SEED_REGEX.sub(new_seed, game_state)

    def save_game_state_screenshot(self, images, html):
        """
        Using HTML parsed from a BYC Game State quote, create a screenshot
        that displays the current game state.
        """

        page_path = Path(f"game/game-state-{self.game_id}-{unique_hash(self.user)}.html")
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

        self.driver.get(page_path.resolve().as_uri())
        screenshot_path = page_path.with_suffix(".png")
        self.driver.save_screenshot(str(screenshot_path))

        images.crop(screenshot_path)

        return screenshot_path

    def _check_script_update(self):
        urgent_script = 'return window.localStorage.getItem("bycUrgent");'
        urgent = self.driver.execute_script(urgent_script)
        if urgent in ("requested", "outdated"):
            logging.info("Updating BYC: %s", urgent)
            with self.SCRIPT_PATH.open('w') as script_file:
                script_file.write(self._load_script())

            self.driver.execute_script('window.localStorage.removeItem("bycUrgent");')
            self.driver.refresh()
            return True

        return False

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

    def check_images(self, images, download=False):
        """
        Check and optionally preload images from the BYC script.
        Detect imageO calls and determine which function it is inside.
        Report any unknown images.
        """

        ok_functions = {
            "textGameState", "characterImage", "locationImage",
            "locationImage2", "nametag", "locationtag", "allyImage",
            "damageImage", "spacer", "vspacer", "heavyImage", "scarImage",
            "IIImage", "VIIImage", "ARImage", "pursuitImage", "jumpImage",
            "pegasusImage", "colonialOneImage", "demetriusImage",
            "rebelBasestarImage", "basestarBridgeImage", "newCapricaImage",
            "cylonImage", "CFBImage", "boardImage"
        }
        seen = set()
        function_regex = re.compile(r"function (\w+)\([^)]*\) {")
        image_regex = re.compile(r"image[MO]\((\d+)\)|\[ima\" \+ bl \+ \"geid=(\d+)\D", re.I)
        with self.SCRIPT_PATH.open('r') as script_file:
            for script in script_file:
                for match in image_regex.finditer(script):
                    for group in match.groups()[1:]:
                        if group is not None:
                            image_id = group
                            break

                    if image_id in seen:
                        continue
                    seen.add(image_id)

                    pos = match.start()
                    start = script.rfind("function ", 0, pos)
                    function = "(unknown)"
                    if start != -1:
                        match = function_regex.match(script, start, pos)
                        if match:
                            function = match.group(1)
                        else:
                            function = "(no match)"

                    image = images.retrieve(image_id, download=download)
                    if image is None and function not in ok_functions:
                        logging.info("Unknown image ID %s in function %s (%d:%d)",
                                     image_id, function, start, pos)
