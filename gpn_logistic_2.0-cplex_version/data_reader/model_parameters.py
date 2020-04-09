import pandas as pd


class ModelParameters:

    # Default Period values
    planning_start = 1
    planning_duration = 2
    hidden_period = 15  # Весь период планирования с учетом скрытой части в днях
    absolute_period_start = 1  # Время начала абсолютного периода
    absolute_period_duration = 14  # Длительность абсолютного периода

    # Operations Parameters
    truck_speed = 40  # скорость БВ
    docs_fill = 0.5  # время заполнения документов на АЗС
    first_thousand_pour = 21 / 60  # скорость слива первой 1000
    thousand_pour = 0.05  # скорость слива топлива на 1000л
    petrol_load_time = 1.6  # Время налива БВ на НБ
    pump_load = 0.1  # уменьшение времени слива секции за счёт использования помпы
    automatic_load = 0.1  # дополнительное время на автоматической АЗС
    mok_docs_fill = 0.5  # время заполнения документов на АЗС
    mok_thousand_pour = 0.1  # скорость слива топлива на 1000л
    mok_pump_load = 0.1  # уменьшение времени слива секции за счёт использования помпы

    # Risk control parameters
    fuel_reserve = 7  # резерв до просыхания АЗС помимо времени движения
    risk_tank_overload = 1  # Занижение бака на уровень потребления в часах

    truck_capacity_part = 1  # часть парка, которая используется для пакета

    "Новый вынос параметров в файл"
    truck_work_cost = 1.6  # Вес в целевой функции для времени движения
    death_penalty = 1.0  # Вес в целевой функции для просушки АЗС
    balance_penalty = 1  # Вес в целевой функции для нарушение баланса
    balance_per_tank = 0.005  # Вес в целевой функции балансирования потребления/поставок в разрезе резервуара. Штраф за единицу нарушения.
    trip_costs = 50  # Вес в целевой функции максимального количества выездов в смену в периоде
    min_turnover = 1.7  # Минимальная оборачиваемость для общего парка

    package_num = None

    file_name = "model_parameters"
    file_path = "/" + file_name + ".xlsx"

    @staticmethod
    def read_parameters(path: str):
        pd_parameters = pd.ExcelFile(path + ModelParameters.file_path).parse(ModelParameters.file_name)
        for index, row in pd_parameters.iterrows():
            setattr(ModelParameters, row['Parameter'], ModelParameters.convert_type(row['Value']))

    @staticmethod
    def convert_type(value: float):
        return int(value) + (value % 1 or 0)
