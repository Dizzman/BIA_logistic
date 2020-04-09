def extract_trip_load_info_asu(row):
    """row = asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty"""
    return row[0]


def extract_trip_load_info_n(row):
    """row = asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty"""
    return row[1]


def extract_asu_n(row):
    return extract_trip_load_info_asu(row), extract_trip_load_info_n(row)


def extract_trip_load_info_section_is_empty(row):
    """row = asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty"""
    return row[7]


def extract_trip_load_info_section_vol(row):
    """row = asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty"""
    return row[6]


def extract_truck_used(row):
    """row = asu, n, sku, shift, truck, section_number, section_volume, is_empty, should_be_empty"""
    return row[4]
