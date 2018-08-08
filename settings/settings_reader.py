import configparser
import os


class SettingsReader:
    root_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_file = os.path.join(root_folder, "settings.ini")

    def __init__(self, property):
        self.config = configparser.ConfigParser()
        self.settings = self.__read(property)

    def __read(self, section):
        self.config.read(self.settings_file)
        dict1 = {}
        options = self.config.options(section)
        for option in options:
            try:
                dict1[option] = self.config.get(section, option)
            except KeyError:
                print("Property not found ({})!".format(option))
                dict1[option] = None
        return dict1

    def get_parameter(self, parameter_name):
        try:
            return self.settings[parameter_name]
        except KeyError:
            raise(KeyError("Parameter {} not found!".format(parameter_name)))
