"""Extractors"""


def extract_asu_from_asu_var_key(key):
    return key[1]


def extract_depot_from_nb_var_key(key):
    return key[1]


def extract_truck_from_asu_var_key(key):
    return key[0]


def extract_truck_from_nb_var_key(key):
    return key[0]


"""Timetable operations"""


def shift_number(time):
    return 2 - time % 2


def truck_decoder(truck):
    return truck % 1000
