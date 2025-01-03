# Bottlestar

- A bot
- Written in Python
- Focused on the Battlestar Galactica (BSG) board game and its expansions
- Contains data on cards and board locations; because of copyright issues, 
  current version does not provide the card text or images; these would require 
  a different set of input data files and/or configuration for external images
- Interfaces (and makes it possible to play) with the By Your Command (BYC) 
  script designed to play BSG on the BoardGameGeek (BGG) forums
- Features search, game state display, and interactive game setups where the 
  bot hosts the game
- Discord and command-line front-ends

## Requirements

- [Python 3.6+](https://www.python.org/downloads/)
- [Virtualenv](https://virtualenv.pypa.io/en/latest/installation.html)
- [ElasticSearch OSS 7](https://www.elastic.co/downloads/elasticsearch-oss)
- [Chrome](https://support.google.com/chrome/answer/95346) or 
  [Chromium](https://www.chromium.org/getting-involved/download-chromium)
- [Chromedriver](https://sites.google.com/a/chromium.org/chromedriver/downloads)
  corresponding to the Chrome/Chromium version
- The code has not been updated for recent updates to the Discord API or BGG, 
  so it may not work and is currently unmaintained

## Setup

- Install the [requirements](#requirements) (which may be available through 
  package managers for your operating system or Python environment, or through 
  the links).
- Ensure the ElasticSearch service is running, usually via `systemctl enable 
  elasticsearch`
- Set up a Python environment in this directory: `virtualenv -p python3 env`
- Activate the Python environment: `source env/bin/activate`
- Install the Python packages: `pip install -r requirements.txt`
- Populate the cards and locations using `python import.py --log INFO`
- Using the developer portal of Discord, create a new, aptly-named
  [Application](https://discordapp.com/developers/applications). To add it to 
  a server of which you are not the owner, it must be public in the Bot 
  settings in the portal. On the OAuth2 settings, select the `bot` scope and 
  select the following permissions to enable all capabilities of the bot: 
  Manage Roles, Manage Channels, Manage Nicknames, View Channels, Send 
  Messages, Manage Messages, Embed Links, Attach Files, Read Message History, 
  Mention Everyone (402910224). Then copy the generated URL to add it to your 
  server or send it to a server owner to let them authorize the bot.
- Create a file `config.yml` and fill it with appropriate values for the
  following settings (most are optional but leaving out hinders functionality):

```yaml
token: # Discord API token from the application in the developer portal
cards_url: # URL to index of various BSG card images
thread_id: # ID of the BGG thread to retrieve game state from
api_url: # URL of the BGG API for image/thread/author lookup
elasticsearch_host: # Hostname where the ElasticSearch endpoint is hosts
script_url: # URL from which to download the BYC script
usernames: # Object where keys are BGG usernames and values discord user IDs
```

# Usage

- Start the Discord bot simply with `python bot.py --log INFO`. We recommend to 
  run this in a `screen` or similar disconnected shell/process.
- Most bot commands can be seen by using `.help` or `!help` (either character 
  works as prefix for all commands).
- Most bot commands are available in the command-line interface without any
  prefix by running `python cmd.py <command> --log INFO`, either through the 
  byc command or separately. Additional arguments may be provided, and use 
  `python cmd.py --help` for optional arguments.

# License

Bottlestar is available under the MIT License. See the [license](LICENSE) file 
for more information.

The Montserrat fonts (which are used for game state display) are available 
under the SIL Open Font License.
