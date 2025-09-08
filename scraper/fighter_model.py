from datetime import date, datetime

class Fighter:
    """
    Creates instances of fighters based off of data scraped from the UFC website.
    """

    def __init__(self, url=None, name=None, height=None, weight=None, reach=None,
                 stance=None, dob=None, slpm=None, stracc=None, sapm=None, strdef=None,
                 tdavg=None, tdacc=None, tddef=None, subavg=None, record=None,
                 mostrecentfight=None, fightswithinufc=None):

        self.url = url
        self.name = name
        self.height = self.height_to_inches(height)
        self.weight = weight
        self.reach = self.reach_conversion(reach)
        self.stance = stance
        self.dob = dob
        self.slpm = self.safe_float(slpm)
        self.stracc = self.percentage_to_float(stracc)
        self.sapm = self.safe_float(sapm)
        self.strdef = self.percentage_to_float(strdef)
        self.tdavg = self.safe_float(tdavg)
        self.tdacc = self.percentage_to_float(tdacc)
        self.tddef = self.percentage_to_float(tddef)
        self.subavg = self.safe_float(subavg)
        self.record = record
        self.most_recent_fight = self.days_since_last_fight(mostrecentfight)
        self.fightswithinufc = fightswithinufc or "0"
        self.weight_class = self.get_weight_class()
        self.fight_count = self.count_fights()
        self.bad_sample = self.bad_sample_flag()

   #Safe Conversions

    @staticmethod
    def safe_float(val):
        """
        Convert to float safely. Returns None if val is None, empty, '--', or invalid.
        """
        if val is None:
            return None
        if isinstance(val, str):
            val = val.strip()
            if val in ("", "--", "N/A"):
                return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def reach_conversion(reach_str):
        """
        Convert reach string like '80"' to integer inches.
        """
        if reach_str is None:
            return None
        if isinstance(reach_str, str):
            reach_str = reach_str.strip()
            if reach_str in ("", "--", "N/A"):
                return None
            try:
                return int(reach_str.strip('"'))
            except ValueError:
                return None
        return None

    @staticmethod
    def days_since_last_fight(date_str):
        """
        Convert last fight date to days ago.
        """
        if date_str is None or date_str in ("Does Not Exist", "--", "N/A", ""):
            return None
        try:
            date_obj = datetime.strptime(date_str, "%b %d, %Y")
            return (datetime.today() - date_obj).days
        except ValueError:
            return None

    @staticmethod
    def percentage_to_float(perc_str):
        """
        Convert percentage string like '48%' to float 0.48.
        """
        if perc_str is None:
            return None
        if isinstance(perc_str, str):
            perc_str = perc_str.strip()
            if perc_str in ("", "--", "N/A"):
                return None
            try:
                return float(perc_str.strip('%')) / 100
            except ValueError:
                return None
        return None

    @staticmethod
    def height_to_inches(height_str):
        """
        Convert height string like 6' 4" to total inches.
        """
        if height_str is None:
            return None
        if isinstance(height_str, str):
            height_str = height_str.strip()
            if height_str in ("", "--", "N/A", ""):
                return None
            start = height_str.find("'")
            end = height_str.find('"')
            if start != -1 and end != -1 and start < end:
                try:
                    feet = int(height_str[:start])
                    inches = int(height_str[start+1:end])
                    return feet * 12 + inches
                except ValueError:
                    return None
        return None

    # Rest of Methods

    def count_fights(self):
        if not self.record or self.record in ("--", "N/A", ""):
            return 0
        if "NC" in self.record:
            nc_index = self.record.find(" (")
            if nc_index != -1:
                self.record = self.record[:nc_index].strip()
        try:
            wins, losses, draws = self.record.split("-")
            return int(wins) + int(losses) + int(draws)
        except ValueError:
            return 0

    def bad_sample_flag(self):
        try:
            return int(self.fightswithinufc) < 3
        except ValueError:
            return True

    def get_weight_class(self):
        ufc_weight_classes = {
            "Strawweight": 115,
            "Flyweight": 125,
            "Bantamweight": 135,
            "Featherweight": 145,
            "Lightweight": 155,
            "Welterweight": 170,
            "Middleweight": 185,
            "Light Heavyweight": 205,
            "Heavyweight": 265
        }
        if not self.weight or self.weight in ('--', 'N/A', ''):
            return 'None'
        try:
            weight_val = int(self.weight.replace('lbs.', '').strip())
            if weight_val > 206:
                return "Heavyweight"
            for group, limit in ufc_weight_classes.items():
                if weight_val in (limit - 1, limit):
                    return group
        except ValueError:
            return 'None'
        return 'None'

    def to_dict(self):
        return {
            "Name": self.name,
            "URL": self.url,
            "Height": self.height,
            "Weight": self.weight,
            "Weight Class": self.weight_class,
            "Reach": self.reach,
            "Stance": self.stance,
            "DOB": self.dob,
            "SLpm": self.slpm,
            "StrAcc": self.stracc,
            "SApM": self.sapm,
            "StrDef": self.strdef,
            "TDAvg": self.tdavg,
            "TDAcc": self.tdacc,
            "TDDef": self.tddef,
            "SubAvg": self.subavg,
            "Record": self.record,
            "Most Recent Fight": self.most_recent_fight,
            "FightCount": self.fight_count,
            "FightsInUFC": self.fightswithinufc,
            "BadSample": self.bad_sample
        }