# БВ
class Car:
    def __init__(self, number, volume_max, volume_min, sections_volumes, drain_side_left,
                 drain_side_right, is_bulky, sec_empty, vehicle_number, trailer_license,
                 is_own, uet, asu_allowed, depot_allowed, shift_size, load_after, section_fuel,
                 cost_per_hour):
        self.number = number
        self.sections_volumes = sections_volumes
        self.volume_max = volume_max
        self.volume_min = volume_min
        self.drain_side_left = drain_side_left
        self.drain_side_right = drain_side_right
        self.is_bulky = is_bulky
        self.sec_empty = sec_empty
        self.vehicle_number = vehicle_number
        self.trailer_license = trailer_license
        self.is_own = is_own
        self.uet = uet
        self.asu_allowed = asu_allowed
        self.depot_allowed = depot_allowed
        self.shift_size = shift_size
        self.load_after = load_after
        self.section_fuel = section_fuel
        self.cost_per_hour = cost_per_hour

    def get_section_amount(self):
        return len(self.sections_volumes)
