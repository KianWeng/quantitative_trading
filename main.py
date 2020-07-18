import argparse
import multiprocessing
from enum import Enum
from time import sleep
from datetime import datetime, time
from logging import INFO

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.setting import SETTINGS

from vnpy.gateway.ctp import CtpGateway
from vnpy.app.cta_strategy import CtaStrategyApp
from vnpy.app.cta_strategy.base import EVENT_CTA_LOG
from vnpy.app.cta_backtester import CtaBacktesterApp
from vnpy.trader.object import HistoryRequest
from vnpy.trader.constant import Exchange
from vnpy.trader.constant import Interval

from vnpy.app.cta_strategy.backtesting import BacktestingEngine, OptimizationSetting
from vnpy.app.cta_strategy.strategies.atr_rsi_strategy import (
    AtrRsiStrategy,
)


STRATEGIES = {
    'AtrRsiStrategy': AtrRsiStrategy
}

SETTINGS["log.active"] = True
SETTINGS["log.level"] = INFO
SETTINGS["log.console"] = True

ctp_setting = {
    "用户名": "",
    "密码": "",
    "经纪商代码": "",
    "交易服务器": "",
    "行情服务器": "",
    "产品名称": "",
    "授权编码": "",
    "产品信息": ""
}

req = HistoryRequest(
            symbol="IF2007",
            exchange=Exchange.CFFEX,
            interval=Interval.MINUTE,
            start=datetime(2020,5,18),
            end=datetime(2020,7,17)
        )

def downloading_history_data(args):
    '''
    download stocks or futures bar data.
    '''
    req = HistoryRequest(
        symbol=args.symbol,
        exchange=Exchange(args.exchange),
        interval=Interval(args.interval),
        start=datetime.strptime(args.startdate, '%Y-%m-%d'),
        end=datetime.strptime(args.enddate, '%Y-%m-%d')
    )

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)
    cta_backtester_engine = main_engine.add_app(CtaBacktesterApp)
    cta_backtester_engine.start_downloading(req.vt_symbol, req.interval, req.start, req.end)

def txt_to_dic(backtesting_setting_file:str):
    dt = {}
    with open(backtesting_setting_file, 'r') as dict_file:
        for line in dict_file:
            (key, value) = line.strip().split(' ')
            dt[key] = float(value)
    # with open语句不必调用f.close()方法
    return dt

def run_single_backtesting(args):
    engine = BacktestingEngine()
    req = HistoryRequest(
        symbol=args.symbol,
        exchange=Exchange(args.exchange),
        interval=Interval(args.interval),
        start=datetime.strptime(args.startdate, '%Y-%m-%d'),
        end=datetime.strptime(args.enddate, '%Y-%m-%d')
    )
    setting = txt_to_dic(args.backtesting_setting_file)
    strategy_class = STRATEGIES[args.strategy_class]

    engine.set_parameters(
        vt_symbol=req.vt_symbol,
        interval=req.interval,
        start=req.start,
        end=req.end,
        rate=args.rate,
        slippage=args.slippage,
        size=args.size,
        pricetick=args.pricetick,
        capital=args.capital    
    )
    engine.add_strategy(strategy_class, setting)
    engine.load_data()
    engine.run_backtesting()
    df = engine.calculate_result()
    engine.calculate_statistics(df)
    engine.show_chart(df)

def show_portafolio(df):
    engine = BacktestingEngine()
    engine.calculate_statistics(df)
    engine.show_chart(df)


def run_child():
    """
    Running in the child process.
    """
    SETTINGS["log.file"] = True

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)
    cta_engine = main_engine.add_app(CtaStrategyApp)
    main_engine.write_log("主引擎创建成功")
    # print(main_engine.engines)

    log_engine = main_engine.get_engine("log")
    event_engine.register(EVENT_CTA_LOG, log_engine.process_log_event)
    main_engine.write_log("注册日志事件监听")

    main_engine.connect(ctp_setting, "CTP")
    main_engine.write_log("连接CTP接口")

    sleep(10)

    cta_engine.init_engine()
    main_engine.write_log("CTA策略初始化完成")

    cta_engine.init_all_strategies()
    sleep(60)   # Leave enough time to complete strategy initialization
    main_engine.write_log("CTA策略全部初始化")

    cta_engine.start_all_strategies()
    main_engine.write_log("CTA策略全部启动")

    while True:
        main_engine.write_log("test log")
        sleep(1)

def run_parent():
    """
    Running in the parent process.
    """
    print("启动CTA策略守护父进程")

    # Chinese futures market trading period (day/night)
    DAY_START = time(8, 45)
    DAY_END = time(19, 30)

    NIGHT_START = time(20, 45)
    NIGHT_END = time(2, 45)

    child_process = None

    while True:
        current_time = datetime.now().time()
        trading = False

        # Check whether in trading period
        if (
            (current_time >= DAY_START and current_time <= DAY_END)
            or (current_time >= NIGHT_START)
            or (current_time <= NIGHT_END)
        ):
            trading = True

        # Start child process in trading period
        if trading and child_process is None:
            print("启动子进程")
            child_process = multiprocessing.Process(target=run_child)
            child_process.start()
            print("子进程启动成功")

        # 非记录时间则退出子进程
        if not trading and child_process is not None:
            print("关闭子进程")
            child_process.terminate()
            child_process.join()
            child_process = None
            print("子进程关闭成功")

        sleep(5)

def parse_args():
    # 解析下载命令
    parser = argparse.ArgumentParser('利用VNPY开源框架对股票或者期货进行量化交易!')
    subparsers = parser.add_subparsers(help="sub-command help!")
    parser_download = subparsers.add_parser('download-data', help='下载回测引擎所需要的数据')
    parser_download.add_argument('-n', '--symbol', default='000001', metavar='N', help='股票或者期货的代码', dest='symbol')
    parser_download.add_argument('-x', '--exchange', default='SZSE', metavar='X', choices=['CFFEX', 'SHFE', 'CZCE', 'DCE', 'INE', 'SSE', 'SZSE', 'SGE'], help='股票或者期货的交易所代码', dest='exchange')
    parser_download.add_argument('-i', '--interval', default='1m', metavar='I', choices=['1m', '1h', 'd', 'w'], help='股票或者期货交易数据的周期1m：1分钟 1h：1小时 d：1天 w：1周', dest='interval')
    parser_download.add_argument('-b', '--startdate', metavar='B', default=datetime.now().strftime('%Y-%m-%d'), help='股票或者期货交易数据的开始日期格式为xxxx-xx-xx', dest='startdate')
    parser_download.add_argument('-e', '--enddate', metavar='E', default=datetime.now().strftime('%Y-%m-%d'), help='股票或者期货交易数据的结束日期格式为xxxx-xx-xx', dest='enddate')
    parser_download.set_defaults(func=downloading_history_data)

    # 解析回测命令
    parser_backtesting = subparsers.add_parser('backtesting', help='股票或者期货回测')
    parser_backtesting.add_argument('-n', '--symbol', default='000001', metavar='N', help='股票或者期货的代码', dest='symbol')
    parser_backtesting.add_argument('-x', '--exchange', default='SZSE', metavar='X', choices=['CFFEX', 'SHFE', 'CZCE', 'DCE', 'INE', 'SSE', 'SZSE', 'SGE'], help='股票或者期货的交易所代码', dest='exchange')
    parser_backtesting.add_argument('-i', '--interval', default='1m', metavar='I', choices=['1m', '1h', 'd', 'w'], help='股票或者期货交易数据的周期1m：1分钟 1h：1小时 d：1天 w：1周', dest='interval')
    parser_backtesting.add_argument('-b', '--startdate', metavar='B', default=datetime.now().strftime('%Y-%m-%d'), help='股票或者期货交易数据的开始日期格式为xxxx-xx-xx', dest='startdate')
    parser_backtesting.add_argument('-e', '--enddate', metavar='E', default=datetime.now().strftime('%Y-%m-%d'), help='股票或者期货交易数据的结束日期格式为xxxx-xx-xx', dest='enddate')
    parser_backtesting.add_argument('-r', '--rate', metavar='R', default=0, type=float, help='股票或者期货的交易手续费费率', dest='rate')
    parser_backtesting.add_argument('-l', '--slippage', metavar='L', default=0, type=float, help='股票或者期货的交易滑点',dest='slippage')
    parser_backtesting.add_argument('-s', '--size', metavar='S',default=0, type=float, help='合约乘数',dest='size')
    parser_backtesting.add_argument('-p', '--pricetick', metavar='P',default=0, type=float, help='价格跳动', dest='pricetick')
    parser_backtesting.add_argument('-c', '--capital', metavar='C', default=100000, type=int, help='回测资金', dest='capital')
    parser_backtesting.add_argument('-f', '--setting-file', metavar='F', default='backtesting_setting.txt', help='回测策略的优化参数', dest='backtesting_setting_file')
    parser_backtesting.add_argument('-t', '--strategy-class', metavar='T',default='AtrRsiStrategy',help='回测策略名字', dest='strategy_class')
    parser_backtesting.set_defaults(func=run_single_backtesting)

    args = parser.parse_args()
    args.func(args)

def main():
    parse_args()

if __name__ == "__main__":
    main()