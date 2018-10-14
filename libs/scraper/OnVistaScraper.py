import os

from bs4 import BeautifulSoup
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
import csv
import re

from libs.model import History, IndexGroup, Stock, MonthClosings, AnalystRatings
from libs.scraper.OnVistaDateUtil import OnVistaDateUtil
from libs.storage import StockStorage, IndexStorage

util = OnVistaDateUtil()

DUMP_FOLDER = "dump/"


def asFloat(txt):
    try:
        return float(txt.replace("%", "").replace(".", "").replace(",", "."))
    except:
        return 0


def scrap_fundamentals(soup):
    fundamental = soup.find("article", {"class": "KENNZAHLEN"})

    # print("Scraping: " + fundamental.find("h2", {"class": "BOX_HEADLINE"}).get_text())

    data_fundamental = {}

    for table in fundamental.findAll("table"):
        name = table.find("th")

        name.em.decompose()
        name.span.decompose()

        tablename = name.get_text().strip()

        header = list(map(lambda th: th.get_text().strip(), table.findAll("th")))

        data = {}
        for index, year in enumerate(header):
            if index > 0 and year != "":
                data[year] = {}

        for row in table.tbody.findAll("tr"):
            for index, column in enumerate(row.findAll("td")):
                if (index == 0):
                    column_name = column.get_text().strip()
                    if (column_name == ""):
                        break
                    data[column_name] = {}
                elif (header[index]):
                    data[column_name][header[index]] = column.get_text().strip()

        data_fundamental[tablename] = data

    return data_fundamental


def get_for_year(values, last_year, last_cross_year):
    if last_year in values:
        return values[last_year]
    if last_cross_year in values:
        return values[last_cross_year]
    return 0


def calc_per_5_years(current_year, fundamentals):
    pers = fundamentals["Gewinn"]["KGV"]
    counter = 0
    per_sum = 0.0
    for key in pers.keys():
        if key <= current_year:
            counter += 1
            per_sum += asFloat(pers[key])

    if counter == 0:
        return 0

    return per_sum / counter


def get_historical_price(storage, month):
    filename = storage.getStoragePath("history-" + str(month), "csv")

    if not os.path.isfile(filename):
        return 0

    with open(filename, mode="r", encoding="utf-8") as f:
        history = csv.DictReader(f, delimiter=';')
        date_ref = (datetime.now() - timedelta(1))
        last_price = "0"

        if month != 0:
            date_ref = date_ref - relativedelta(months=month)

        for day in history:
            if day["Datum"].strip() == "":
                continue

            date = datetime.strptime(day["Datum"].strip(), "%d.%m.%Y")

            if date > date_ref:
                break

            if day["Schluss"]:
                last_price = day["Schluss"]

        return asFloat(last_price)


def scrap_ratings(stock, stock_storage: StockStorage):
    filename = stock_storage.getStoragePath("ratings", "html")
    ratings = {
        "kaufen": 0,
        "halten": 0,
        "verkaufen": 0
    }

    if os.path.isfile(filename):
        with open(filename, mode="r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, 'html.parser')

            for row in soup.findAll("tr"):
                columns = row.findAll("td")

                type = columns[0].get_text().strip()
                count = columns[1]

                count.div.decompose()

                ratings[type] = int(count.get_text().strip())

    stock.ratings = AnalystRatings(ratings["kaufen"], ratings["halten"], ratings["verkaufen"])

    return stock


def get_market_capitalization(fundamentals, last_year, last_cross_year):
    market_capitalization = asFloat(
        get_for_year(fundamentals["Marktkapitalisierung"]["Marktkapitalisierung in Mio. EUR"], last_year,
                     last_cross_year))
    if market_capitalization > 0:
        market_capitalization = market_capitalization * 1000000

    return market_capitalization


def scrap(stock: Stock, stock_storage: StockStorage):

    with open(stock_storage.getStoragePath("fundamental", "html"), mode="r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, 'html.parser')

        last_year = util.get_last_year()
        last_cross_year = util.get_last_cross_year()
        current_year = util.get_current_year()
        current_cross_year = util.get_current_cross_year()
        next_year = util.get_next_year()
        next_cross_year = util.get_next_cross_year()

        fundamentals = scrap_fundamentals(soup)

        stock.roi = asFloat(
            get_for_year(fundamentals["Rentabilität"]["Eigenkapitalrendite"], last_year, last_cross_year))
        stock.ebit_margin = asFloat(
            get_for_year(fundamentals["Rentabilität"]["EBIT-Marge"], last_year, last_cross_year))

        stock.equity_ratio = asFloat(
            get_for_year(fundamentals["Bilanz"]["Eigenkapitalquote"], last_year, last_cross_year))

        stock.per_5_years = calc_per_5_years(current_year, fundamentals)

        stock.per = asFloat(get_for_year(fundamentals["Gewinn"]["KGV"], current_year, current_cross_year))

        stock_price_today = get_historical_price(stock_storage, 0)
        stock_price_6month = get_historical_price(stock_storage, 6)
        stock_price_1year = get_historical_price(stock_storage, 12)

        stock.history = History(stock_price_today, stock_price_6month, stock_price_1year)

        stock.monthClosings = get_month_closings(stock_storage)

        stock.eps_current_year = asFloat(
            get_for_year(fundamentals["Gewinn"]["Gewinn pro Aktie in EUR"], current_year, current_cross_year))

        stock.eps_next_year = asFloat(
            get_for_year(fundamentals["Gewinn"]["Gewinn pro Aktie in EUR"], next_year, next_cross_year))

        stock.market_capitalization = get_market_capitalization(fundamentals, last_year, last_cross_year)

    stock = scrap_ratings(stock, stock_storage)

    return stock


def scrap_index(indexGroup: IndexGroup, index_storage: IndexStorage):
    base_path = indexGroup.name + "/" + indexGroup.name

    index_price_today = get_historical_price(index_storage, 0)

    index_price_6month = get_historical_price(index_storage, 6)

    index_price_1year = get_historical_price(index_storage, 12)

    indexGroup.history = History(index_price_today, index_price_6month, index_price_1year)

    indexGroup.monthClosings = get_month_closings(index_storage)


def get_month_closings(storage):
    closings = MonthClosings()

    closings.closings = [
        get_cloasing_price(storage, 4),
        get_cloasing_price(storage, 3),
        get_cloasing_price(storage, 2),
        get_cloasing_price(storage, 1)
    ]

    return closings


def get_cloasing_price(storage, month):
    filename = storage.getStoragePath("history-" + str(month), "csv")

    if not os.path.isfile(filename):
        return 0

    with open(filename, mode="r", encoding="utf-8") as f:
        history = csv.DictReader(f, delimiter=';')
        date_ref = (datetime.now() - timedelta(1))
        last_price = "0"

        if month != 0:
            date_ref = date_ref - relativedelta(months=month)

        for day in history:
            if day["Datum"].strip() == "":
                continue
            if day["Schluss"]:
                last_price = day["Schluss"]

        return asFloat(last_price)


def read_stocks(indexGroup):
    with open(DUMP_FOLDER + indexGroup.name + "/" + indexGroup.name + ".list.html", mode="r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, 'html.parser')

        article = soup.find("article", {"class": "top-flop-box"})
        table = article.find("table")

        for row in table.findAll("tr"):
            columns = row.findAll("td")

            if len(columns) == 0:
                continue

            firstCol = columns[0]

            link = firstCol.find("a")

            if link.get("href") and link.get("href").startswith("/"):
                matches = re.search("\/aktien\/(.*)-Aktie-(.*)", link.get("href"))
                name = matches.group(1)
                stock_id = matches.group(2)

                field = firstCol.find("span").get_text().strip()

                indexGroup.add_stock(stock_id, name, field)