from data_reader.model_parameters import ModelParameters
from general_model.main_model import Model
from testpack.checker import check_results
import json


def run_testpack(only_one=None):
    out_struct = []
    
    total_number_of_tests = 0
    total_successful_tests = 0

    with open('./testpack/testpack_config.json') as config:
        data = json.load(config)
        for test_element in data['tests']:
            if only_one:
                if only_one == int(test_element['id']):
                    test_id = int(test_element['id'])
                    test_desc = test_element['desc']

                    input_path = data['path'].format(test_id)

                    ModelParameters.read_parameters(path=input_path + str(test_id))

                    model = Model(scenario=test_id,
                                path=input_path,
                                planning_start=ModelParameters.planning_start,
                                planning_duration=ModelParameters.planning_duration)
                    
                    result_of_the_test = {}

                    try:
                        model.general_start()
                    except:
                        result_of_the_test = {'passed': False, 
                        'message': ["Проблема разрешимости модели (Infeasible и проч.)"]}
                        pass
                    else:
                        result_of_the_test = check_results(test_id, test_desc)

                    out_struct.append(result_of_the_test)
                    total_number_of_tests += 1

                    if result_of_the_test['passed']:
                        total_successful_tests += 1
            else:
                test_id = int(test_element['id'])
                test_desc = test_element['desc']

                input_path = data['path'].format(test_id)

                ModelParameters.read_parameters(path=input_path + str(test_id))

                model = Model(scenario=test_id,
                            path=input_path,
                            planning_start=ModelParameters.planning_start,
                            planning_duration=ModelParameters.planning_duration)

                result_of_the_test = {}

                try:
                    model.general_start()
                except:
                    result_of_the_test = {'passed': False, 
                    'message': ["Проблема разрешимости модели. Модель, возможно, не имеет допустимых решений"]}
                    result_of_the_test['_id'] = test_id
                    result_of_the_test['_desc'] = test_desc
                    pass
                else:
                    result_of_the_test = check_results(test_id, test_desc)

                out_struct.append(result_of_the_test)
                total_number_of_tests += 1

                if result_of_the_test['passed']:
                    total_successful_tests += 1

    result = dict()

    result['test_results'] = out_struct
    result['_total'] = total_number_of_tests
    result['_sucess'] = "{}/{}".format(
        total_successful_tests, total_number_of_tests)
    result['_failed'] = "{}/{}".format(
        total_number_of_tests - total_successful_tests, total_number_of_tests
    )
    result['_sucess_perc'] = "{:.1f}%".format(
        total_successful_tests / total_number_of_tests * 100
    )

    with open('testpack/data/result.json', 'w', encoding='utf-8') as outfile:
        json.dump(result, outfile, indent=4, sort_keys=True, ensure_ascii=False)
