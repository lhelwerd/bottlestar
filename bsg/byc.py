"""
Standalone interpreter of the BYC script that runs it in a sandbox and stores
game states.
"""

# Modules:
# Selenium for executing the JavaScript in a realistic browser sandbox
# Some marshal/pickle/json/other storage format for storing game states
# across restarts
from base64 import urlsafe_b64encode
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
    BUTTON_ATTRIBUTES = ("class", "innerText")

    def __init__(self, dialog):
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

class ByYourCommand:
    """
    By Your Command game.
    """

    SCRIPT_PATH = Path("byc.js")

    def __init__(self, game_id, script_url):
        self.game_id = game_id
        self.script_url = script_url
        self.load()

    def __del__(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def load(self):
        # Load script
        if not self.SCRIPT_PATH.exists():
            script = self.load_script()
            with self.SCRIPT_PATH.open('w') as script_file:
                script_file.write(script)

        # Setup Selenium web driver
        self.load_driver()

    def load_driver(self):
        options = Options()
        options.headless = True
        options.add_argument("allow-file-access-from-files")
        self.driver = webdriver.Chrome(chrome_options=options)

    def run_page(self, user, state):
        try:
            current_user = self.driver.find_element_by_tag_name("a")
            if current_user.get_attribute("innerText") != user:
                raise ValueError("Context switched")

            state = state[-1:]
        except (NoSuchElementException, ValueError):
            page_path = Path(f"page-{urlsafe_b64encode(user.encode()).decode()}.html")
            script_url = self.SCRIPT_PATH.resolve().as_uri()
            with page_path.open('w') as page_file:
                page_file.write(f'''<html><head><title>BYC</title></head>
                    <body>
                        <a href="/collection/user/{user}">{user}</a>
                        <textarea></textarea>
                        <script src="{script_url}"></script>
                    </body>
                </html>''')

            self.driver.get(page_path.resolve().as_uri())

        #print(self.driver.page_source)
        #print(self.driver.find_element_by_tag_name("script").get_attribute("innerText"))

        try:
            dialog = Dialog(self.wait_for_dialog())
        except TimeoutException:
            return self.driver.find_element_by_tag_name("textarea").get_attribute("value")

        # TODO: If the dialog has only one option (OK), then just click it and 
        # yield the message?
        for choice in state:
            print(choice)
            if dialog.input and not isinstance(choice, int):
                dialog.input.send_keys(choice)
                button = dialog.element.find_element_by_class_name("ok")
            else:
                button = dialog.element.find_element_by_css_selector(f"button:nth-child({choice})")
                print(button.get_attribute("innerText"))

            button.click()

            try:
                self.wait_for_dialog(wait=invisibility_of_element(dialog.element))
            except TimeoutException:
                raise RuntimeError("Dialog did not disappear")

            try:
                dialog = Dialog(self.wait_for_dialog())
            except TimeoutException:
                return self.driver.find_element_by_tag_name("textarea").get_attribute("value")

        # Read alerts
        print(dialog.element.get_attribute("innerHTML"))

        print(self.driver.get_log("browser"))
        return dialog

    def wait_for_dialog(self, wait=None):
        if wait is None:
            wait = visibility_of_element_located((By.CLASS_NAME, "dialog"))
        return WebDriverWait(self.driver, 5).until(wait)

    def load_script(self):
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
