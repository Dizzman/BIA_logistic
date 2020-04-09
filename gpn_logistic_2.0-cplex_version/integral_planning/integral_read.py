from data_reader.input_data import StaticData
import pandas as pd
from integral_planning.functions import day_calculation_by_shift


class IntegralRead:
    def __init__(self, path, data: StaticData, period_start: int):
        self.path = path
        self.data = data
        self.period_start = period_start
        self.pd_flows = pd.DataFrame
        self.departures = {}

        'Read data'
        self.read_from_xlsx()

    def read_from_xlsx(self):
        excel_file = pd.ExcelFile(self.path)

        self.pd_flows = excel_file.parse('volumes')
        pd_departures = excel_file.parse('departures')

        # =========== Save integral model =============
        writer = pd.ExcelWriter('./output/integral_model_from_%d_to_%d.xlsx' % (self.period_start, self.period_start + self.data.parameters.absolute_period_duration - 1))
        self.pd_flows.to_excel(writer, 'volumes')
        pd_departures.to_excel(writer, 'departures')
        writer.save()

        # ==============================================
        pd_departures = pd_departures.groupby(['id_asu', 'time'], as_index=False).sum()
        self.departures = {(int(row['id_asu']), int(row['time'])): int(row['departures']) for idx, row in pd_departures.iterrows()}

    def allocation_update(self, time):
        loads = self.pd_flows.loc[self.pd_flows['time'] == time]
        day_number = day_calculation_by_shift(time)

        for idx, row in loads.iterrows():
            asu_n_day = (int(row['id_asu']), int(row['n']), time)
            self.data.asu_depot_reallocation[asu_n_day] = int(row['depot'])
            if int(row['depot']) != self.data.asu_depot[int(row['id_asu'])]:
                self.data.asu_reallocated.setdefault(time, []).append(int(row['id_asu']))
            else:
                if int(row['id_asu']) in self.data.asu_reallocated.get(time, []):
                    self.data.asu_reallocated[time].remove(int(row['id_asu']))
