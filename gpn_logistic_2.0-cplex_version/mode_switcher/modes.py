import cProfile
import os
import time

from copy import deepcopy

from data_reader.calc_percent import percents
from data_reader.input_data import StaticData, Parameters
from data_reader.model_parameters import ModelParameters
from data_splitter.data_splitter import DSplitter
from general_model.main_model import Model, VALIDATION_ONLY_MODE, TESTPACK_MODE, LAUNCH_AFTER_CALC_VALIDATION
from integral_planning.integral_planning import IntegralModel, ConstraintSwitcher
from output_writer.output_stations_state import OutputCreatorStations
from testpack import testpack
from validation.validate_output import validate_result
from data_merge.data_merge import Merge
from asu_nb_connecting.update_static_data import update_static_data


def enable_collection(func):

    pr = cProfile.Profile()
    pr.enable()

    scenario = 2
    path = './input/scenario_'

    func(str(scenario), str(path))

    pr.disable()
    pr.dump_stats('./output/profiler.prof')


class Mode:

    @staticmethod
    def normal_mode(scenario, path):

        directory = os.path.dirname("./output/trip_optimization/")
        if not os.path.exists(directory):
            os.makedirs(directory)

        if not VALIDATION_ONLY_MODE and not TESTPACK_MODE:
            start_time = time.time()

            ModelParameters.read_parameters(path=path + str(scenario))
            model = Model(scenario=scenario, path=path,
                          planning_start=ModelParameters.planning_start,
                          planning_duration=ModelParameters.planning_duration)

            percents.display_percent()
            "Запуск расчета"
            model.general_start(False)

            percents.display_percent()
            solution_calculation_time = time.time() - start_time
            print(('-' * 20 + 'Total computation time = %d' + '-' * 20) % solution_calculation_time)
            print("<FOR_USER>\nРасчет завершен!\n</FOR_USER>")
        else:
            ModelParameters.read_parameters(path=path + str(scenario))

        # Валидация результатов

        if (LAUNCH_AFTER_CALC_VALIDATION or VALIDATION_ONLY_MODE) and not TESTPACK_MODE:
            validate_result(input_path=path + str(scenario),
                            output_path='output/',
                            planning_start=ModelParameters.planning_start,
                            planning_duration=ModelParameters.planning_duration)

        if TESTPACK_MODE:
            testpack.run_testpack()

    @staticmethod
    def split_mode(scenario, path):

        ModelParameters.read_parameters(path=path + str(scenario))
        parameters = Parameters()  # Parameters initialization
        data = StaticData(path + scenario + '/', parameters)  # Initial data initialization
        initial_state = data.initial_fuel_state.copy()

        output_states_collection_test = OutputCreatorStations(data=data,
                                                              parameters=parameters,
                                                              init_states=initial_state,
                                                              time_zero=parameters.absolute_period_start - 1)

        data_splitter_test = DSplitter(data=data,
                                       parameters=parameters,
                                       output_states_collection=output_states_collection_test)

        data_splitter_test.generate_outputs(path + scenario + '/', './output/split_data/')

    @staticmethod
    def merge_mode(scenario, path):
        merge = Merge(path + scenario + '/merge/')
        merge.write_data('./output/')

    @staticmethod
    def package_mode(scenario, path):

        ModelParameters.read_parameters(path=path + str(scenario))
        parameters = Parameters()  # Parameters initialization
        data = StaticData(path + scenario + '/', parameters)  # Initial data initialization
        initial_state = data.initial_fuel_state.copy()

        # Генерируем информацию для работы интегральной модели с фиктивной АЗС

        updated_data = deepcopy(data)
        update_static_data(updated_data)

        """Сборщик состояний баков с течением времени"""
        output_states_collection = OutputCreatorStations(data=updated_data,
                                                         parameters=parameters,
                                                         init_states=initial_state,
                                                         time_zero=parameters.absolute_period_start - 1)

        # Построение интегральной модели для общей НБ

        integral_model = IntegralModel(parameters=parameters,
                                       data=updated_data,
                                       initial_state=initial_state,
                                       period_start=parameters.absolute_period_start,
                                       period_duration=parameters.absolute_period_duration,
                                       constraint_switcher=ConstraintSwitcher(path + str(scenario)),
                                       previous_period_loaded_sku={row['sku']: 0 for idx, row in
                                                                   updated_data.absolute_period_consumption.iterrows()},
                                       output_states_collection=output_states_collection)

        integral_model.optimize()
        flow_data, departures_data, departures_dict = integral_model.output_data(write_results=True)

    @staticmethod
    def detailed_mode(scenario, path):
        directory = os.path.dirname("./output/trip_optimization/")
        if not os.path.exists(directory):
            os.makedirs(directory)

        if not VALIDATION_ONLY_MODE and not TESTPACK_MODE:
            start_time = time.time()

            ModelParameters.read_parameters(path=path + str(scenario))
            model = Model(scenario=scenario, path=path,
                          planning_start=ModelParameters.planning_start,
                          planning_duration=ModelParameters.planning_duration)

            percents.display_percent()
            "Запуск расчета"
            model.general_start(True, True)

            percents.display_percent()
            solution_calculation_time = time.time() - start_time
            print(('-' * 20 + 'Total computation time = %d' + '-' * 20) % solution_calculation_time)
            print("<FOR_USER>\nРасчет завершен!\n</FOR_USER>")
        else:
            ModelParameters.read_parameters(path=path + str(scenario))

        # Валидация результатов

        if (LAUNCH_AFTER_CALC_VALIDATION or VALIDATION_ONLY_MODE) and not TESTPACK_MODE:
            validate_result(input_path=path + str(scenario),
                            output_path='output/',
                            planning_start=ModelParameters.planning_start,
                            planning_duration=ModelParameters.planning_duration)

        if TESTPACK_MODE:
            testpack.run_testpack()

    def run(self, mode: str):
        if mode == 'normal':
            "Обычный (полный) режим запуска модели"
            enable_collection(self.normal_mode)
        elif mode == 'split':
            "Разбиение данных на пакеты"
            enable_collection(self.split_mode)
        elif mode == 'merge':
            "Объединение результатов интегральных моделей"
            enable_collection(self.merge_mode)
        elif mode == 'package':
            "Интегральное планирование со средней НБ"
            enable_collection(self.package_mode)
        elif mode == 'detailed':
            "Расчет детальной модели с учетом привязок из файла"
            enable_collection(self.detailed_mode)
        else:
            print('No mode name: <<%s>>' % mode)
