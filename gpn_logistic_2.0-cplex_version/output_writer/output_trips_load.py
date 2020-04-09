from detailed_planning.dp_parameters import DParameters
from data_reader.input_data import StaticData
import pandas as pd
from output_writer.extract_function import *
from detailed_planning.trip_optimization import is_asu_set_death
from detailed_planning.functions import calculate_time_to_death


class OutputCreatorTrips:
    def __init__(self, set_direct: dict, set_distribution: dict, set_direct_double: dict, set_distribution_double: dict,
                 set_double_distribution_double: dict, depot_queue: dict, pd_parameters: DParameters, data: StaticData):
        self.set_direct = set_direct  # {asu, truck: existence}
        self.set_distribution = set_distribution  # {asu1, asu2, truck: existence}
        self.set_direct_double = set_direct_double  # {asu1, asu2, truck: existence}
        self.set_distribution_double = set_distribution_double  # {asu1, asu2, asu3, truck: existence}
        self.set_double_distribution_double = set_double_distribution_double
        self.depot_queue = depot_queue
        self.pd_parameters = pd_parameters
        self.data = data
        self.trip_load_info = []

        '''Extract truck load results. Pandas DataFrame.'''
        self.trip_load_info_update()

    def clear_empty_loads(self, loads_sequence):
        return [self.pd_parameters.asu_n_decoder(asu_n) for asu_n in loads_sequence if asu_n != 0]

    @staticmethod
    def add_load_section(loaded_volumes: dict, key, volume):
        if key in loaded_volumes:
            loaded_volumes[key] += volume
        else:
            loaded_volumes[key] = volume

    def section_load_row_generation(self, loads_sequence, section_number, truck_num, number_of_sections, truck_sections, is_empty,
                                    should_be_empty, numeration_jump, trip_number):
        real_section = section_number
        reduced_section = section_number
        if numeration_jump:
            reduced_section -= numeration_jump

        """Check, is the section filled?"""
        if not is_empty:
            asu_n = self.pd_parameters.asu_n_decoder(loads_sequence[reduced_section])
            asu = asu_n[0]
            n = asu_n[1]
            sku = self.data.tank_sku[asu_n]
            asu_set = set(asu_tank[0] for asu_tank in loads_sequence if asu_tank)
            is_critical = 1 if is_asu_set_death(asu_set, self.pd_parameters, self.data) else 0
            days_to_death = min(calculate_time_to_death(asu, self.pd_parameters, self.data) for asu in asu_set if asu)
        else:
            asu, n, sku, is_critical, days_to_death = 0, 0, 0, 0, 0
        shift = self.pd_parameters.time
        sec_number = number_of_sections - real_section
        section_volume = truck_sections[real_section]

        """asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty, 'trip_number', 'is_critical', 'days_to_death"""
        return [asu, n, sku, shift, truck_num, sec_number, section_volume, is_empty, should_be_empty, trip_number, is_critical, days_to_death]

    def update_truck_loads(self, loads_sequence, section_number, truck_num, number_of_sections, truck_sections, load_by_truck, numeration_jump, trip_number):
        section_skip = 0
        if numeration_jump:
            section_skip += numeration_jump

        if loads_sequence[section_number - section_skip] != 0:
            """asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty, 'trip_number', 'is_critical', 'days_to_death"""
            load_row = self.section_load_row_generation(loads_sequence=loads_sequence,
                                                        section_number=section_number,
                                                        truck_num=truck_num,
                                                        number_of_sections=number_of_sections,
                                                        truck_sections=truck_sections,
                                                        is_empty=0,
                                                        should_be_empty=0,
                                                        numeration_jump=numeration_jump,
                                                        trip_number=trip_number)
            load_by_truck.append(load_row)
        else:
            """asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty, 'trip_number', 'is_critical'"""
            load_row = self.section_load_row_generation(loads_sequence=loads_sequence,
                                                        section_number=section_number,
                                                        truck_num=truck_num,
                                                        number_of_sections=number_of_sections,
                                                        truck_sections=truck_sections,
                                                        is_empty=1,
                                                        should_be_empty=0,
                                                        numeration_jump=numeration_jump,
                                                        trip_number=trip_number)
            load_by_truck.append(load_row)

    def loads_and_sections(self, truck_num, loads_sequence, trip_number):
        """Number of empty section"""
        empty_section_numbers = self.data.empty_section_number(truck_num, self.clear_empty_loads(loads_sequence))
        """Truck sections volumes"""
        truck_sections = self.data.vehicles[truck_num].sections_volumes
        """Number of truck sections"""
        number_of_sections = len(truck_sections)
        load_by_truck = []
        for section_number in range(number_of_sections):
            """If there isn't necessarily empty section"""
            if empty_section_numbers == [0]:
                # """If section isn't empty"""
                # if loads_sequence[section_number] != 0:
                self.update_truck_loads(loads_sequence, section_number, truck_num, number_of_sections, truck_sections, load_by_truck, False, trip_number)
            else:
                """If section is before empty section"""
                if number_of_sections - section_number in empty_section_numbers:
                    """asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty, 'trip_number', 'is_critical', 'days_to_death'"""
                    load_row = [0, 0, 0, self.pd_parameters.time, truck_num, number_of_sections - section_number, truck_sections[section_number], 1, 1, trip_number, 0, 0]
                    load_by_truck.append(load_row)
                else:
                    self.update_truck_loads(loads_sequence, section_number, truck_num, number_of_sections, truck_sections, load_by_truck,
                                            self.numeration_jump(number_of_sections - section_number, empty_section_numbers), trip_number)
        return load_by_truck

    def numeration_jump(self, section_number, empty_sections):
        jump = 0
        for empty_section in empty_sections:
            if section_number < empty_section:
                jump += 1
        return jump


    """Trips loads: direct trip"""
    def direct_trip_load(self):
        loads_info = []
        for asu, truck_num in self.set_direct:
            # loads_volumes = self.pd_parameters.truck_load_volumes[truck_num, [asu]]
            loads_sequence = self.pd_parameters.truck_load_sequence[truck_num, (asu,)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence, 1))
            # truck_sections = self.data.sections_to_load(truck_num, set([asu_n for asu_n in loads_sequence]))

        return loads_info

    """Trips loads: distribution trip"""
    def distribution_trip_load(self):
        loads_info = []
        for asu1, asu2, truck_num in self.set_distribution:
            # loads_volumes = self.pd_parameters.truck_load_volumes[truck_num, [asu]]
            loads_sequence = self.pd_parameters.truck_load_sequence[truck_num, (asu1, asu2)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence, 1))
            # truck_sections = self.data.sections_to_load(truck_num, set([asu_n for asu_n in loads_sequence]))

        return loads_info

    """Trips loads: double trip"""
    def double_trip_load(self):
        loads_info = []
        for asu1, asu2, truck_num in self.set_direct_double:
            # loads_volumes = self.pd_parameters.truck_load_volumes[truck_num, [asu]]
            loads_sequence1 = self.pd_parameters.truck_load_sequence[truck_num, (asu1,)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence1, 1))

            loads_sequence2 = self.pd_parameters.truck_load_sequence[truck_num, (asu2,)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence2, 2))
            # truck_sections = self.data.sections_to_load(truck_num, set([asu_n for asu_n in loads_sequence]))

        return loads_info

    """Trips loads: double trip with distribution"""
    def double_distribution_trip_load(self):
        loads_info = []
        for asu1, asu2, asu3, truck_num in self.set_distribution_double:

            truck_queue = [(route, time) for depot, time, truck, route, trip_number in self.depot_queue
                           if truck == truck_num]
            route = truck_queue[0][0]
            if len(route) == 2:
                direct_trip_number = 1 if len(route[0]) == 1 else 2
            else:
                truck_queue.sort(key=lambda x: x[1])
                direct_trip_number = 2 if len(truck_queue[-1][0][0]) == 1 else 1

            loads_sequence1 = self.pd_parameters.truck_load_sequence[truck_num, (asu1, asu2)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence1, 3 - direct_trip_number))

            loads_sequence2 = self.pd_parameters.truck_load_sequence[truck_num, (asu3,)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence2, direct_trip_number))

        return loads_info

    """Trips loads: double trip with distribution"""
    def double_distribution_double_trip_load(self):
        loads_info = []
        for asu1, asu2, asu3, asu4, truck_num in self.set_double_distribution_double:
            loads_sequence1 = self.pd_parameters.truck_load_sequence[truck_num, (asu1, asu2)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence1, 1))

            loads_sequence2 = self.pd_parameters.truck_load_sequence[truck_num, (asu3, asu4)]
            loads_info.extend(self.loads_and_sections(truck_num, loads_sequence2, 2))

        return loads_info

    """Extract loads in certain format for each trip type"""
    def trip_load_info_update(self):
        self.trip_load_info.extend(self.direct_trip_load())
        self.trip_load_info.extend(self.distribution_trip_load())
        self.trip_load_info.extend(self.double_trip_load())
        self.trip_load_info.extend(self.double_distribution_trip_load())
        self.trip_load_info.extend(self.double_distribution_double_trip_load())

    """Convert load results to dict"""
    def trip_load_info_to_dict(self):
        trip_load_info_dict = {}

        for row in self.trip_load_info:
            asu = extract_trip_load_info_asu(row)
            n = extract_trip_load_info_n(row)
            is_empty = extract_trip_load_info_section_is_empty(row)
            section_vol = extract_trip_load_info_section_vol(row)
            if is_empty != 1 and asu != 0:
                self.add_load_section(trip_load_info_dict, (asu, n), section_vol)
        return trip_load_info_dict

    """Extract used trucks"""
    def truck_used_set(self):
        truck_set = []

        for row in self.trip_load_info:
            truck = extract_truck_used(row)
            truck_set.append(truck)

        return list(set(truck_set))

    """Prepare output in pandas DataFrame."""
    def collect_into_pandas(self, write_results=False):
        tripLoadDataFrame = pd.DataFrame(self.trip_load_info,
                                         columns=['asu', 'n', 'sku', 'shift', 'truck', 'section_number', 'section_volume', 'is_empty',
                                                  'should_be_empty', 'trip_number', 'is_critical', 'days_to_death'])

        if write_results:
            writer = pd.ExcelWriter('./output/truck_loads_shift_%d.xlsx' % self.pd_parameters.time)
            tripLoadDataFrame.to_excel(writer, 'truck_loads')
            writer.save()

        return tripLoadDataFrame
