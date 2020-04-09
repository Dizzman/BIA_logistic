import matplotlib.pyplot as plt
import pandas as pd
import datetime as dt


def plot_vehicle_graph(timetable: pd.DataFrame, shift_size, shift_start_time, vehicles_busy_hours, vehicles_cut_off,
                       vehicles_busy, vehicles, file_name):

    vehicle_graph(timetable, shift_size, shift_start_time, vehicles_busy_hours, vehicles_cut_off,
                  vehicles_busy, vehicles, file_name)
    vehicle_graph(timetable, shift_size, shift_start_time, vehicles_busy_hours, vehicles_cut_off,
                  vehicles_busy, vehicles, file_name, use_vehicle_name=True)


def vehicle_graph(timetable: pd.DataFrame, shift_size, shift_start_time, vehicles_busy_hours, vehicles_cut_off,
                  vehicles_busy, vehicles, file_name, use_vehicle_name=False):
    colormap = {
        #'Moving': '#65v407f',
        #'Waiting_depot_queue': '#ff7f7f',
        #'Waiting_asu_queue': '#ffd47f',
        #'Waiting_asu_window': '#ffff7f',
        #'Load': '#7f7fff',
        #'Unload': '#73e5a1'
        'Moving': 'y',
        'Waiting_depot_queue': 'brown',
        'Waiting_asu_queue': 'coral',
        'Waiting_asu_window': 'peru',
        'Load': 'skyblue',
        'Unload': 'yellowgreen',
        'Cut_off': 'silver',
        'Busy': 'gainsboro',
        'Short_shift': 'gainsboro'
    }
    lineWidth = 15
    timeScale = 1
    rotation = 90

    plt.figure(figsize=(25, 15))

    if not timetable.empty:
        # Время начала периода планирования
        first_shift = int(min(timetable['shift']))
        last_shift = int(max(timetable['shift']))
        min_time = min(0.0, int(min(timetable[timetable['shift'] == first_shift]['start_time'])))
        max_time = float(max(row['end_time'] + (row['shift'] - first_shift) * shift_size for i, row in timetable.iterrows())) + 1
        start_time = shift_start_time + shift_size * (1 - first_shift % 2)
        finish_time = start_time + (last_shift - first_shift + 1) * shift_size
        start = dt.datetime(year=1, month=1, day=2, hour=start_time)

        plt.figure(figsize=(max(max_time // 1, 25), len(vehicles) // 2.9))

        date_time = start + dt.timedelta(hours=min_time)
        x_axis, x_values = [min_time], [date_time.strftime('%H:%M')]
        y_axis, y_values, y_names = [], [], []

        sorted_vehicles_list = list(vehicles.keys())
        sorted_vehicles_list.sort()

        for truck in vehicles:
            y_names.append(vehicles[truck].vehicle_number)
            y_values.append(truck)
            y_number = y_values.index(truck)
            y_axis.append(y_number)

            plt.hlines(y_number, 0, 0.1, colors='white', lw=0.1)

            for shift in range(first_shift, last_shift + 1):
                shift_time = (shift - first_shift) * shift_size
                start_of_shift = vehicles_busy_hours.get((truck, shift), (0,))[0]
                if start_of_shift > 0:
                    color = colormap['Busy']
                    plt.hlines(y_number, shift_time, shift_time + start_of_shift, colors=color, lw=lineWidth + 1.5)
                truck_shift_size = vehicles[truck].shift_size
                if truck_shift_size < shift_size:
                    color = colormap['Short_shift']
                    plt.hlines(y_number, shift_time + truck_shift_size, shift_time + shift_size,
                               colors=color, lw=lineWidth + 1.5)
                cut_off = vehicles_cut_off.get((truck, shift), 0)
                if cut_off and shift_time + truck_shift_size - cut_off < max_time:
                    color = colormap['Cut_off']
                    plt.hlines(y_number, shift_time + truck_shift_size - cut_off,
                               min(shift_time + truck_shift_size, max_time),
                               colors=color, lw=lineWidth + 1.5)
                busy = (truck, shift) in vehicles_busy
                if busy:
                    color = colormap['Busy']
                    plt.hlines(y_number, shift_time, shift_time + shift_size, colors=color, lw=lineWidth + 1.5)

        timetable.reset_index(inplace=True)
        for index, row in timetable.iterrows():
            y_number = y_values.index(row['truck'])
            shift_time = (row['shift'] - first_shift) * shift_size
            color = colormap['Moving']
            if row['operation'] == 'перемещение':
                color = colormap['Moving']
            elif row['operation'] == 'слив':
                color = colormap['Unload']
            elif row['operation'] == 'налив':
                color = colormap['Load']
            elif row['operation'] == 'ожидание':
                if timetable['operation'].tolist()[index + 1] != 'перемещение':
                    color = colormap['Waiting_depot_queue']
                else:
                    asu = timetable['location'].tolist()[index + 2]
                    drain_time = timetable['start_time'].tolist()[index + 2]
                    asu_drain = timetable[(timetable['operation'] == 'слив') & (timetable['location'] == asu)
                                          & (timetable['truck'] != row['truck'])]['end_time']
                    if asu_drain.empty or all(round(end, 1) != round(drain_time, 1) for end in asu_drain):
                        color = colormap['Waiting_asu_window']
                    else:
                        color = colormap['Waiting_asu_queue']

            plt.hlines(y_number, shift_time + row['start_time'], shift_time + row['end_time'],
                       colors=color, lw=lineWidth)
            if row['operation'] in ('слив', 'налив'):
                plt.text(shift_time + (row['end_time'] + row['start_time']) / 2 -
                         len(str(row['location'])) / 15, y_number - 0.15, row['location'])

            time = x_axis[-1]
            while max(shift_time + row['end_time'], finish_time - start_time) > x_axis[-1]:
                time += timeScale
                x_axis.append(time)
                date_time = start + dt.timedelta(hours=time)
                x_values.append(date_time.strftime('%H:%M'))

        time = x_axis[-1] + timeScale
        plt.hlines(y_axis[0] + 0.2, time + 0.1, time + 0.2, colors='white', lw=0.1)

        plt.xticks(x_axis, x_values)
        if use_vehicle_name:
            plt.yticks(y_axis, y_names)
        else:
            plt.yticks(y_axis, y_values)

    plt.xlabel('Time')
    plt.ylabel('Vehicle')
    plt.xticks(rotation=rotation)

    plt.plot(0, 0, colormap['Moving'], label='Moving')
    plt.plot(0, 0, colormap['Unload'], label='Unload')
    plt.plot(0, 0, colormap['Load'], label='Load')
    plt.plot(0, 0, colormap['Waiting_depot_queue'], label='Waiting depot queue')
    plt.plot(0, 0, colormap['Waiting_asu_window'], label='Waiting asu window')
    plt.plot(0, 0, colormap['Waiting_asu_queue'], label='Waiting asu queue')
    plt.plot(0, 0, colormap['Short_shift'], label='Short shift size')
    plt.plot(0, 0, colormap['Busy'], label='Busy')
    plt.plot(0, 0, colormap['Cut_off'], label='Cut off')

    plt.legend()
    plt.title('Vehicle timetable')
    plt.grid()

    if use_vehicle_name:
        file_name += '_names'
    plt.savefig(file_name + '.png', bbox_inches='tight')
    plt.close('all')


if __name__ == '__main__':
    timetable_file = './timetable.xlsx'
    timetable = pd.ExcelFile(timetable_file).parse('full_timetable')
    shift_size, shift_start_time = 12, 8
    plot_vehicle_graph(timetable, shift_size, shift_start_time, {}, {}, {}, {}, 'vehicle_graph')
