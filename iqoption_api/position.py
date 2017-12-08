import logging
import time
from math import log10, floor


class Position():
    def __init__(self, data):
        self.min_watermark = 100
        self.max_watermark = -95
        self.current_watermark = -95
        self.__parse_data(data)

    def __parse_data(self, data):
        """
        Parse data from API. Unchanged fields will have a None value, so let's filter them out first.
        """
        data = {k: v for k, v in data.items() if v is not None}
        prevmin = self.min_watermark
        prevmax = self.max_watermark
        prevcurrent = self.current_watermark
        orders = None
        if (("orders" in data and len(data["orders"]) == 0)) and ("orders" not in data and hasattr(self, 'orders')):
            orders = self.orders

        self.__dict__ = data
        self.max_watermark = prevmax
        self.min_watermark = prevmin
        self.current_watermark = prevcurrent
        if orders:
            self.orders = orders
        self.logger = logging.getLogger("iqoption_api.position")

    def update(self, data):
        prev = self.is_open()
        self.__parse_data(data)
        if self.is_open() != prev:
            logger = logging.getLogger("iqoption_api.position.close")
            self.logger.info("posisiton closed")
            logger.info('{},{},{},{},{},{},{},{},{}'.format(self.update_at, self.create_at, self.close_at, self.id, self.min_watermark, self.max_watermark, self.current_watermark, self.close_reason, self.instrument_id))

    def update_watermarks(self, percent):
        self.min_watermark = min(self.min_watermark, percent)
        self.max_watermark = max(self.max_watermark, percent)
        self.current_watermark = percent

    def update_order(self, data):
        """{'instrument_id_escape': 'USDNOK', 'basic_stoplimit_amount': 68.0, 'take_profit_price': None, 'stop_lose_price': None, 'tpsl_extra': None, 'instrument_strike_value': None, 'instrument_type': 'forex', 'instrument_id': 'USDNOK', 'instrument_underlying': 'USDNOK', 'instrument_active_id': 168, 'instrument_expiration': None, 'instrument_strike': None, 'instrument_dir': None, 'id': 197997486, 'user_id': 25309108, 'user_balance_id': 43902542, 'user_balance_type': 4, 'position_id': 105120553, 'create_at': 1512136901477, 'update_at': 1512136902059, 'execute_at': 1512136902080, 'side': 'sell', 'type': 'market', 'status': 'filled', 'execute_status': 'trade', 'count': 410.19, 'leverage': 50, 'underlying_price': 8.28878, 'avg_price': 8.28878, 'avg_price_enrolled': 8.28878, 'client_platform_id': 9, 'limit_price': 0.0, 'stop_price': 0.0, 'currency': 'USD', 'margin': 67.999493, 'spread': 0.002149999999998542, 'commission_amount': 0.0, 'commission_amount_enrolled': 0.0, 'extra_data': {'amount': 68000000, 'auto_margin_call': False, 'paid_for_commission': 3.2978681700337323e-229, 'use_token_for_commission': False, 'paid_for_commission_enrolled': 3.2978681700337323e-229}, 'time_in_force': 'good_till_cancel', 'time_in_force_date': None, 'index': 268787403}"""
        order_id = data["id"]
        saved = False
        for k, order in enumerate(self.orders):
            if order['id'] == order_id:
                self.orders[k] = data
                saved = True
        if not saved:
            self.orders.append(data)
        self.logger.debug(self.orders)
        if data["type"] == "stop" and data["status"] != "canceled":
            self.logger.debug("updated stop_lose_order_id to {} of position {}".format(order_id, self.id))
            self.stop_lose_order_id = order_id
        if data["type"] == "limit" and data["status"] != "canceled":
            self.logger.debug("updated take_profit_order_id to {}  of position {}".format(order_id, self.id))
            self.take_profit_order_id = order_id
        # else:
        #     self.logger.info("got order update type: {}".format(data["type"]))

    def update_tpsl(self, data):
        pass

    def get_data(self):
        return self.__dict__

    def is_open(self):
        return self.__dict__["status"] == "open"

    def is_sell(self):
        return self.buy_avg_price_enrolled == 0.0

    def is_buy(self):
        return self.sell_avg_price_enrolled == 0.0

    def stop_loss(self):
        try:
            return [order["stop_price"] for order in self.orders if order["id"] == self.stop_lose_order_id][0]
        except (IndexError, AttributeError):
            self.logger.debug("found no stop order, calculation of posistion loss for {}".format(self.id))
            if self.is_sell():
                return (1 + 0.95/self.leverage) * self.sell_avg_price_enrolled
            else:
                return (1 - 0.95/self.leverage) * self.buy_avg_price_enrolled

    def get_current_win(self, currentprice):
        if self.is_sell():
            # sell
            price = self.sell_avg_price_enrolled
            percent_with_lev = (1-currentprice/price) * self.leverage

        elif self.is_buy():
            # buy
            price = self.buy_avg_price_enrolled
            percent_with_lev = (1-price/currentprice) * self.leverage
        else:
            self.logger.warn("invalid/unknown enrollment price")
            return 0.0
        # pure guess. No clue how the margin is calculated
        return percent_with_lev - 0.02

    def get_stoploss(self, percent_buffer, current_price):
        if self.is_sell():
            return self.round_sig(current_price + percent_buffer * self.get_open_price() / self.leverage)
        elif self.is_buy():
            return self.round_sig(self.get_open_price() / ((self.get_open_price() / current_price) + (percent_buffer / self.leverage)))
        else:
            raise ValueError("unknown")

    def round_sig(self, x, sig=8):
        try:
            return round(x, sig-int(floor(log10(abs(x))))-1)
        except ValueError:
            return 0

    def get_takeprofit(self, percent_buffer, current_price):
        if self.is_sell():
            return self.round_sig(current_price - percent_buffer * self.get_open_price() / self.leverage)
        elif self.is_buy():
            return self.round_sig(self.get_open_price() / ((self.get_open_price() / current_price) - (percent_buffer / self.leverage)))
        else:
            raise ValueError("unknown")

    def get_open_price(self):
        if self.is_sell():
            return self.sell_avg_price_enrolled
        elif self.is_buy():
            return self.buy_avg_price_enrolled
        else:
            raise ValueError("unknown")

    def get_age(self):
        return time.time() - self.create_at / 1000

    def get_invest(self):
        try:
            return self.extra_data['amount'] / 1000000
        except:
            self.logger.error('no extra_data on {}'.format(self.id))
            return 1
