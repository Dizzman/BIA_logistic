import pandas as pd
from validation import validate_output


class CheckersCollection:
    @staticmethod
    def checker_25000():
        result_of_this_test = {'passed': True,
                               'message': []}

        asu_states = pd.read_excel('./output/asu_states_until_shift_2.xlsx', index_col=0)
        num_of_rows = len(asu_states)
        for line_id in range(0, num_of_rows):
            if asu_states.iloc[line_id]['asu_state'] < asu_states.iloc[line_id]['death_vol']:
                result_of_this_test['passed'] = False
                result_of_this_test['message'].append("Просыхание. В результирующем файле объём топлива ниже допустимого минимума")
                return result_of_this_test

        if result_of_this_test['passed']:
            result_of_this_test['message'] = ["Тест успешно пройден"]

        return result_of_this_test

    @staticmethod
    def checker_25001():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        added_asu = set()
        for line_id in range(0, num_of_rows):
            added_asu.add(timetable.at[line_id, 'asu'])

        if len(added_asu) < 2:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("В данном кейсе должен быть рейс с развозом")
        else:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        
        return result_of_this_test

    @staticmethod
    def checker_25002():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        added_asu = set()
        added_trucks = set()
        for line_id in range(0, num_of_rows):
            added_asu.add(timetable.at[line_id, 'asu'])
            added_trucks.add(timetable.at[line_id, 'truck'])

        if not (added_asu == 2 and added_trucks == 1):
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("В данном кейсе должен быть рейс с развозом")
        else:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        
        return result_of_this_test

    @staticmethod
    def checker_25003():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
        
        if 1000 <= total_volume <= 3000:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume == 0.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Просыхание из-за отсутствия поставок в первую смену"]
        elif total_volume > 3000.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Переполнение резервуара"]

        return result_of_this_test

    @staticmethod
    def checker_25004():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test

    @staticmethod
    def checker_25005():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test

    @staticmethod
    def checker_25006():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test
    
    @staticmethod
    def checker_25006():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test

    @staticmethod
    def checker_25007():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test


    @staticmethod
    def checker_25007():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 0.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = timetable.at[line_id, 'time']

        if 1000 <= total_volume <= 1125 and delivery_time < 6.0:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        elif total_volume > 1125.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Превышен допустимый объём поставки. При доп.поставке в смену 2 резервуар будет переполнен"]
        
        if 1000 <= total_volume <= 1125 and delivery_time > 6.0:
            result_of_this_test['passed'] = False
            result_of_this_test['message'].append("Пересыхание резервуара в первую смену.")

        return result_of_this_test


    @staticmethod
    def checker_25008():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')
        
        num_of_rows = len(timetable)
        
        total_volume = 0.0
        delivery_time = 9999.0

        for line_id in range(0, num_of_rows):
            asu_id = timetable.at[line_id, 'asu']
            delivered = timetable.at[line_id, 'section_volume']
            shift = timetable.at[line_id, 'shift']
            
            if asu_id != 0 and shift == 1:
                total_volume += delivered
                delivery_time = min(delivery_time, timetable.at[line_id, 'time'])

        if total_volume >= 50000.0:
            if delivery_time > 2.0:
                result_of_this_test['message'] = ["Тест успешно пройден"]
            else:
                result_of_this_test['passed'] = False
                result_of_this_test['message'] = ["Некорректное время ранней поставки (2 ч.) - допущено просыхание резервуара"]
        else:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Недостаточный объём поставки - допущено просыхание резервуара"]

        return result_of_this_test


    @staticmethod
    def checker_25009():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='full_timetable')
        
        num_of_rows = len(timetable)
        
        timeline = {}

        for time in range(0, 1440):
            timeline[time] = 0

        for line_id in range(0, num_of_rows):
            if timetable.at[line_id, 'operation'] == 'налив':
                start_time = int(timetable.at[line_id, 'start_time']) * 60 + 1
                end_time = int(timetable.at[line_id, 'end_time']) * 60

                for time in range(start_time, end_time + 1):
                    timeline[time] += 1

        for time in range(0, 1440):
            if timeline[time] > 1:
                result_of_this_test['passed'] = False
                result_of_this_test['message'] = ["Допущено превышение кол-ва БВ на НБ"]
                return result_of_this_test
        
        result_of_this_test['message'] = ["Тест успешно пройден"]

        return result_of_this_test

    @staticmethod
    def checker_25010():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='timetable')

        num_of_rows = len(timetable)

        timeline = {}

        delivery_in_1st_shift = False
        for line_id in range(0, num_of_rows):
            if int(timetable.at[line_id, 'shift']) == 1:
                delivery_in_1st_shift = True

        if delivery_in_1st_shift:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        else:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Допущено просыхание"]

        return result_of_this_test

    @staticmethod
    def checker_25011():
        result_of_this_test = {'passed': True,
                               'message': []}

        timetable = pd.read_excel('./output/timetable.xlsx', index_col=0, sheet_name='full_timetable')

        num_of_rows = len(timetable)

        timeline = {}

        is_passed = True
        for line_id in range(0, num_of_rows):
            if timetable.at[line_id, 'operation'] == 'слив':
                time = float(timetable.at[line_id, 'start_time'])
                if time < 6.0:
                    is_passed = False

        if is_passed:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        else:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Слив на АЗС в недопустимое время"]

        return result_of_this_test

    @staticmethod
    def checker_25012():
        result_of_this_test = {'passed': True,
                               'message': []}

        delivery_in_1st_shift = False
        timetable = pd.read_excel('./output/timetable.xlsx', sheet_name='full_timetable')

        num_of_rows = len(timetable)

        delivery_in_1st_shift = False

        for line_id in range(0, num_of_rows):
            if int(timetable.at[line_id, 'shift']) == 1 and timetable.at[line_id, 'operation'] == 'слив':
                delivery_in_1st_shift = True

        if delivery_in_1st_shift:
            result_of_this_test['message'] = ["Тест успешно пройден"]
        else:
            result_of_this_test['passed'] = False
            result_of_this_test['message'] = ["Не осуществлена поставка в первую смену"]

        return result_of_this_test


def check_results(test_id, test_description):
    m = globals()['CheckersCollection']()
    checker = getattr(m, 'checker_{}'.format(test_id))

    result_of_this_test = checker()
    result_of_this_test['_id'] = test_id
    result_of_this_test['_desc'] = test_description

    return result_of_this_test
