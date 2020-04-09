from os import listdir
from os.path import isfile, join
import pandas as pd
import os


class Merge:
    def __init__(self, path):
        self.path = path
        self.name = 'integral_model_from'
        self.files_names = [f for f in listdir(path)
                            if isfile(join(path, f)) and f[:len(self.name)] == self.name]

    def data_merge(self):
        """
        Функция чтения результатов интегральных моделей
        Returns: volumes, departures (оба объекти pandas)

        """
        data_frames_volumes = []
        data_frames_departures = []
        for file_name in self.files_names:
            read_file = pd.ExcelFile(self.path + file_name)
            data_frames_volumes.append(read_file.parse('volumes'))
            data_frames_departures.append(read_file.parse('departures'))

        volumes_pd = pd.concat(data_frames_volumes, ignore_index=True)
        departures_pd = pd.concat(data_frames_departures, ignore_index=True)

        return volumes_pd, departures_pd

    def write_data(self, dir_out):
        """
        Запись файла объединенных интегральных моделей
        Args:
            dir_out: путь к выходной папке

        Returns: Ничего

        """
        if not os.path.exists(dir_out):
            os.makedirs(dir_out)

        volumes, departures = self.data_merge()
        writer = pd.ExcelWriter(dir_out + 'integral_model.xlsx')
        volumes.to_excel(writer, sheet_name='volumes')
        departures.to_excel(writer, sheet_name='departures')
        writer.save()


if __name__ == '__main__':
    merge = Merge('../input/scenario_2/merge/')
    merge.write_data('./output/')
