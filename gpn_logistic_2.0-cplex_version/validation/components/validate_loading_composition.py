def validate_loading_composition(parameters, deliveries, stations, vehicles, log):
    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    # Проставляем объектам Delivery значения sku согласно резервуарам

    for delivery in deliveries:
        current_asu = delivery.asu
        current_n = delivery.n

        for station in stations:
            for reservoir in station.reservoirs:
                if station.asu_id == current_asu and reservoir.n == current_n:
                    delivery.sku = reservoir.sku

    # Проходим по рейсам и проверяем загрузку

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        trips_inside_this_shift = {}

        # Соберем информацию о каждом рейсе БВ в графике

        for delivery in deliveries:
            if delivery.truck:
                if delivery.shift == checking_shift:
                    if (delivery.truck, delivery.trip_number) in trips_inside_this_shift:
                        trips_inside_this_shift[(delivery.truck, delivery.trip_number)].append(delivery)
                    else:
                        trips_inside_this_shift[(delivery.truck, delivery.trip_number)] = []
                        trips_inside_this_shift[(delivery.truck, delivery.trip_number)].append(delivery)

        for key, trips in trips_inside_this_shift.items():
            current_vehicle = None

            current_truck_id = key[0]
            current_sku = set()
            current_sku_categories = set()

            for vehicle in vehicles:
                if vehicle.id == current_truck_id:
                    current_vehicle = vehicle

            for delivery in trips:
                if delivery.sku:
                    current_sku.add(delivery.sku)
                    if delivery.sku <= 4:
                        current_sku_categories.add('petrol')
                    elif 5 <= delivery.sku <= 13:
                        current_sku_categories.add('diesel')

            current_mode = None

            if 'petrol' in current_sku_categories and 'diesel' in current_sku_categories:
                current_mode = 'np_mix'
            elif 'petrol' in current_sku_categories:
                current_mode = 'np_petrol'
            elif 'diesel' in current_sku_categories:
                current_mode = 'np_diesel'

            if current_mode == 'np_mix':
                sections_should_be_empty = current_vehicle.np_mix
            elif current_mode == 'np_petrol':
                sections_should_be_empty = current_vehicle.np_petrol
            elif current_mode == 'np_diesel':
                sections_should_be_empty = current_vehicle.np_diesel

            for delivery in trips:
                if delivery.section_number in sections_should_be_empty:
                    if not delivery.is_empty:
                        log.add_message(module='validate_loading_composition',
                                        shift=checking_shift,
                                        truck_id=current_truck_id,
                                        message='Некорректная загрузка БВ (Секция {} не должна быть загружена)'.
                                        format(delivery.section_number))

                if delivery.is_empty and not delivery.should_be_empty:
                    log.add_message(module='validate_loading_composition',
                                    shift=checking_shift,
                                    truck_id=current_truck_id,
                                    message='Пустая секция БВ (Секции {} БВ {} не рекомендуется быть пустой)'.
                                    format(delivery.section_number, delivery.truck))
