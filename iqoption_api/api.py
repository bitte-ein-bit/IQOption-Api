import requests
import websocket
import time
from threading import Thread
from datetime import datetime
import json
from .position import Position
import logging


class IQOption():

    practice_balance = 0
    real_balance = 0
    server_time = 0
    positions = {}
    instruments_categories = ["cfd", "forex", "crypto", "digital-option"]
    top_assets_categories = ["forex", "crypto", "binary"]
    instruments_to_id = {}
    id_to_instruments = {}
    market_data = {}
    stoploss_update = {}

    def __init__(self, username, password, host="iqoption.com"):

        self.username = username
        self.password = password
        self.host = host
        self.session = requests.Session()
        self.generate_urls()
        self.socket = websocket.WebSocketApp(self.socket_url, on_open=self.on_socket_connect, on_message=self.on_socket_message, on_close=self.on_socket_close, on_error=self.on_socket_error)
        self.logger = logging.getLogger("iqoption_api")
        self.client_platform_id = 9

    def generate_urls(self):
        """Generates Required Urls to operate the API"""

        self.api_url = "https://{}/api/".format(self.host)
        self.socket_url = "wss://{}/echo/websocket".format(self.host)
        self.login_url = self.api_url+"login"
        self.profile_url = self.api_url+"profile"
        self.change_account_url = self.profile_url+"/"+"changebalance"
        self.getprofile_url = self.api_url+"getprofile"

    def login(self):
        """Login and set Session Cookies"""

        data = {"email": self.username, "password": self.password}
        self.__login_response = self.session.request(url=self.login_url, data=data, method="POST")
        requests.utils.add_dict_to_cookiejar(self.session.cookies, dict(platform=self.client_platform_id))
        json_login_response = self.__login_response.json()
        if json_login_response["isSuccessful"]:
            self.__ssid = self.__login_response.cookies["ssid"]
            self.parse_account_info(json_login_response)
            self.start_socket_connection()
            time.sleep(1)  # artificial delay to complete socket connection
            self.get_instruments()
            self.get_top_assets()
            self.get_positions()
            time.sleep(1)  # artificial delay to populate symbols
        return json_login_response["isSuccessful"]

    def parse_account_info(self, jsondata):
        """Parse Account Info"""

        self.real_balance = jsondata["result"]["balances"][0]["amount"]/1000000
        self.practice_balance = jsondata["result"]["balances"][1]["amount"]/1000000
        self.currency = jsondata["result"]["currency"]
        self.account_to_id = {"real": jsondata["result"]["balances"][0]["id"], "practice": jsondata["result"]["balances"][1]["id"]}
        self.id_to_account = {jsondata["result"]["balances"][0]["id"]: "real", jsondata["result"]["balances"][1]["id"]: "practice"}
        self.active_account = ["real" if jsondata["result"]["balance_type"] == 1 else "practice"][0]
        self.active_account_id = self.account_to_id[self.active_account]
        self.balance = jsondata["result"]["balance"]
        self.logger.info("active account: {0}".format(self.active_account))
        self.logger.info("active account id: {0}".format(self.active_account_id))

    def on_socket_message(self, socket, message):
        message = json.loads(message)
        messagename = message["name"]
        message = message["msg"]

        if messagename == "timeSync":
            self.__server_timestamp = message
            self.server_time = datetime.fromtimestamp(self.__server_timestamp/1000)
            self.tick = self.server_time.second

        elif messagename in ["tradersPulse", "tournament", "activeCommissionChange", "order-placed-temp", "front"]:
            pass

        elif messagename == "heartbeat":
            self.answer_heartbeat(message)

        elif messagename == "profile":
            self.parse_profile_message(message)

        elif messagename == "position-changed":
            self.parse_position_message(message)

        elif messagename == "newChartData":
            self.parse_new_chart_data_message(message)

        elif messagename == "top-assets":
            self.parse_top_assets_message(message)

        elif messagename == "instruments":
            self.parse_instruments_message(message)

        elif messagename == "available-leverages":
            self.parse_available_leverages(message)

        elif messagename == "order-changed":
            self.parse_order_changed(message)

        elif messagename == "tpsl-changed":
            self.parse_tpsl_changed(message)

        elif messagename == "positions":
            self.parse_positions_message(message)

        else:
            self.logger.info("unknown message: {0}".format(messagename))
            self.logger.debug(message)
            pass

    def on_socket_connect(self, socket):
        """Called on Socket Connection"""

        self.initial_subscriptions()
        self.logger.debug("on socket connect")

    def on_socket_error(self, socket, error):
        """Called on Socket Error"""
        self.logger.exception(error)

    def on_socket_close(self, socket):
        """Called on Socket Close"""

    def start_socket_connection(self):
        """Start Socket Connection"""
        self.socket_thread = Thread(target=self.socket.run_forever).start()

    def stop_socket_connection(self):
        self.socket.close()

    def send_socket_message(self, name, msg, log=True):
        data = {"name": name, "msg": msg}
        if log:
            self.logger.debug("send_socket_message: {0}".format(data))
        self.socket.send(json.dumps(data))

    def initial_subscriptions(self):
        self.send_socket_message("ssid", self.__ssid)
        self.send_socket_message("subscribe", "tradersPulse")

    def parse_profile_message(self, message):
        if "balance" in message and "balance_id" in message and "currency" in message:
            account = self.id_to_account[message["balance_id"]]
            self.__dict__["{}_balance".format(account)] = message["balance"]

        elif "balance" in message and "balance_id" in message:
            self.balance = message["balance"]
            self.active_account = self.id_to_account[message["balance_id"]]

    def answer_heartbeat(self, heartbeattime):
        self.send_socket_message("heartbeat", {"userTime": "{:.0f}".format(time.time()*100), "heartbeatTime": heartbeattime}, False)

    def parse_position_message(self, message):
        id = message["id"]
        self.logger.debug("parsed position: {0}".format(id))
        self.logger.debug("parsed position: {}".format(message))
        if id in self.positions:
            self.positions[id].update(message)
        else:
            self.positions[id] = Position(message)

    def parse_order_changed(self, message):
        """{'instrument_id_escape': 'USDNOK', 'basic_stoplimit_amount': 68.0, 'take_profit_price': None, 'stop_lose_price': None, 'tpsl_extra': None, 'instrument_strike_value': None, 'instrument_type': 'forex', 'instrument_id': 'USDNOK', 'instrument_underlying': 'USDNOK', 'instrument_active_id': 168, 'instrument_expiration': None, 'instrument_strike': None, 'instrument_dir': None, 'id': 197997486, 'user_id': 25309108, 'user_balance_id': 43902542, 'user_balance_type': 4, 'position_id': 105120553, 'create_at': 1512136901477, 'update_at': 1512136902059, 'execute_at': 1512136902080, 'side': 'sell', 'type': 'market', 'status': 'filled', 'execute_status': 'trade', 'count': 410.19, 'leverage': 50, 'underlying_price': 8.28878, 'avg_price': 8.28878, 'avg_price_enrolled': 8.28878, 'client_platform_id': 9, 'limit_price': 0.0, 'stop_price': 0.0, 'currency': 'USD', 'margin': 67.999493, 'spread': 0.002149999999998542, 'commission_amount': 0.0, 'commission_amount_enrolled': 0.0, 'extra_data': {'amount': 68000000, 'auto_margin_call': False, 'paid_for_commission': 3.2978681700337323e-229, 'use_token_for_commission': False, 'paid_for_commission_enrolled': 3.2978681700337323e-229}, 'time_in_force': 'good_till_cancel', 'time_in_force_date': None, 'index': 268787403}"""
        """{'instrument_id_escape': 'GBPAUD', 'basic_stoplimit_amount': None, 'take_profit_price': None, 'stop_lose_price': None, 'tpsl_extra': None, 'instrument_strike_value': None, 'instrument_type': 'forex', 'instrument_id': 'GBPAUD', 'instrument_underlying': 'GBPAUD', 'instrument_active_id': 104, 'instrument_expiration': None, 'instrument_strike': None, 'instrument_dir': None, 'id': 198025634, 'user_id': 25309108, 'user_balance_id': 43902542, 'user_balance_type': 4, 'position_id': 105107359, 'create_at': 1512137346595, 'update_at': 1512137346595, 'execute_at': None, 'side': 'buy', 'type': 'stop', 'status': 'new', 'execute_status': 'new', 'count': 1937.89, 'leverage': 50, 'underlying_price': None, 'avg_price': None, 'avg_price_enrolled': None, 'client_platform_id': 0, 'limit_price': None, 'stop_price': 1.778058, 'currency': 'USD', 'margin': None, 'spread': None, 'commission_amount': None, 'commission_amount_enrolled': None, 'extra_data': {'use_token_for_commission': False, 'auto_margin_call': False}, 'time_in_force': 'good_till_cancel', 'time_in_force_date': None, 'index': 268830312}"""
        pos_id = message["position_id"]
        if pos_id in self.positions:
            self.positions[pos_id].update_order(message)

    def parse_tpsl_changed(self, message):
        """{'name': 'change-tpsl', 'version': '1.0', 'body': {'position_id': 105112592, 'take_profit': 1.5644423049999998, 'stop_lose': 1.5669506169999998, 'extra': {'stop_lose_type': 'percent', 'take_profit_type': 'percent'}}}}"""
        # print(self.positions[message['position_id']].get_data())
        # pass

    def parse_positions_message(self, message):
        if message["total"] > 0:
            for pos in message["positions"]:
                self.parse_position_message(pos)

    def parse_new_chart_data_message(self, message):
        symbol = message["symbol"]
        self.logger.debug("parse_new_chart_data_message: {0}".format(message))

        if symbol in self.market_data:
            self.market_data[symbol][message["time"]] = message
        else:
            self.market_data[symbol] = {message["time"]: message}

    def get_latest_chart_data(self, symbol):
        """returns something like this: {'active_id': 102, 'symbol': 'GBPCAD', 'bid': 1.7419499999999999, 'ask': 1.74222, 'value': 1.742085, 'volume': 0, 'time': 1512058717, 'closed': False, 'show_value': 1.742085, 'buy': 1.74222, 'sell': 1.7419499999999999}"""
        if symbol in self.market_data:
            last = sorted(self.market_data[symbol].keys())[-1]
            return self.market_data[symbol][last]
        else:
            return None

    def parse_top_assets_message(self, message):
        instrument_type = message["instrument_type"]
        temp = {}
        for ele in message["data"]:
            temp[ele["active_id"]] = ele["active_id"]
        self.__dict__["{}_top_assets".format(instrument_type)] = temp

    def parse_available_leverages(self, message):
        self.logger.debug("parse_available_leverages: {}".format(message))
        instrument_type = message["instrument_type"]
        temp = {}
        for ele in message["leverages"]:
            temp[self.id_to_instruments[ele["active_id"]]] = ele["regulated"]
        self.__dict__["{}_leverages".format(instrument_type)] = temp

    def parse_instruments_message(self, message):
        instrument_type = message["type"]
        self.logger.debug("parse_instruments_message: {}".format(message))
        temp = {}
        for ele in message["instruments"]:
            temp[ele["id"]] = ele["active_id"]
            self.instruments_to_id[ele["id"]] = ele["active_id"]
            self.id_to_instruments[ele["active_id"]] = ele["id"]
        self.__dict__["{}_instruments".format(instrument_type)] = temp
        self.get_leverage(instrument_type, list(temp.values()))

    def change_account(self, account_type):
        """Change active account `real` or `practice`"""

        data = {"balance_id": self.account_to_id[account_type.lower()]}
        self.session.request(url=self.change_account_url, data=data, method="POST")
        self.update_info()
        return self.active_account

    def update_info(self):
        """Update Account Info"""

        self.parse_account_info(self.session.request(url=self.getprofile_url, method="GET").json())

    def get_top_assets(self):
        for ele in self.top_assets_categories:
            self.send_socket_message("sendMessage", {"name": "get-top-assets", "version": "1.1", "body": {"instrument_type": ele}})

    def get_instruments(self):
        for ele in self.instruments_categories:
            self.send_socket_message("sendMessage", {"name": "get-instruments", "version": "1.0", "body": {"type": ele}})

    def get_positions(self, instrument_type=""):
        if instrument_type != "":
            self.send_socket_message("sendMessage", {"name": "get-positions", "version": "1.0", "body": {"user_balance_id": self.active_account_id, "instrument_type": instrument_type}})
            return
        for instrument_type in self.instruments_categories:
            self.send_socket_message("sendMessage", {"name": "get-positions", "version": "1.0", "body": {"user_balance_id": self.active_account_id, "instrument_type": instrument_type}})

    def get_open_positions(self, market=None):
        tmp = self.positions
        tmp = sorted(tmp.values(), key=lambda x: x.id)
        if market is None:
            return [pos for pos in tmp if pos.is_open()]
        else:
            return [pos for pos in tmp if pos.is_open() and pos.instrument_id == market]

    def get_leverage(self, instrument_type, actives):
        self.send_socket_message("sendMessage", {"name": "get-available-leverages", "version": "2.0", "body": {"instrument_type": instrument_type, "actives": json.dumps(actives)}})

    def subscribe_market(self, market_name=None, market_id=None):
        if market_name:
            market_id = self.instruments_to_id.get(market_name)
        self.send_socket_message("subscribeMessage", {"name": "quote-generated", "version": "1.0", "params": {"routingFilters": {"active_id": market_id}}})

    def unsubscribe_market(self, market_name=None, market_id=None):
        if market_name:
            market_id = self.instruments_to_id.get(market_name)
        self.send_socket_message("unsubscribeMessage", {"name": "quote-generated", "version": "1.0", "params": {"routingFilters": {"active_id": market_id}}})

    def buy_forex(self, amount, market, leverage, side):
        if market not in self.forex_instruments:
            self.logger.warning("invalid market in buy_forex: {}".format(market))
            return
        if leverage not in self.forex_leverages[market]:
            self.logger.warning("invalid leverage in buy_forex: {}".format(leverage))
            return
        # "{"name":"sendMessage","request_id":"1511993239_839844713","msg":{"name":"place-order-temp","version":"3.0","body":{"user_balance_id":43902542,"client_platform_id":"9","instrument_type":"forex","instrument_id":"EURUSD","side":"buy","type":"market","amount":1,"leverage":500,"limit_price":0,"stop_price":0,"use_token_for_commission":false}}}"
        self.logger.info("Buying {} of {} with direction {} and leverage {}".format(amount, market, side, leverage))
        self.send_socket_message("sendMessage", {
                                  "name": "place-order-temp",
                                  "version": "3.0",
                                  "body": {
                                      "user_balance_id": self.active_account_id,
                                      "client_platform_id": self.client_platform_id,
                                      "instrument_type": "forex",
                                      "instrument_id": market,
                                      "side": side,
                                      "type": "market",
                                      "amount": amount,
                                      "leverage": leverage,
                                      "limit_price": 0,
                                      "stop_price": 0,
                                      "use_token_for_commission": False
                                  }})

    def update_stoploss(self, position_id, stop_lose_value, take_profit_value=None):
        if position_id in self.stoploss_update and time.time() - self.stoploss_update[position_id] < 0.5:
            self.logger.debug("skipping stop loss update, last update less than 500ms away")
            return
        self.stoploss_update[position_id] = time.time()
        self.logger.info("stop loss: {} -> {}:{}".format(position_id, stop_lose_value, take_profit_value))
        self.send_socket_message("sendMessage", {"name": "change-tpsl", "version": "1.0", "body": {"position_id": position_id, "take_profit": take_profit_value, "stop_lose": stop_lose_value, "extra": {"stop_lose_type": "percent", "take_profit_type": "percent"}}})
