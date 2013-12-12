# -*- coding: utf-8 -*-

# Copyright (c) 2013 Johannes Baiter. All rights reserved.
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
spreads CLI code.
"""

from __future__ import division, unicode_literals, print_function

import argparse
import logging
import os
import sys
import time

import colorama
import spreads.confit as confit

from spreads.workflow import Workflow
from spreads.plugin import (get_devices, get_driver, get_pluginmanager,
                            setup_plugin_config, get_relevant_extensions)
from spreads.util import DeviceException, ColourStreamHandler

# Kudos to http://stackoverflow.com/a/1394994/487903
try:
    from msvcrt import getch
except ImportError:
    def getch():
        """ Wait for keypress on stdin.

        :returns: unicode -- Value of character that was pressed

        """
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def capture(workflow):
    if len(workflow.devices) != 2:
        raise DeviceException("Please connect and turn on two"
                              " pre-configured devices! ({0} were"
                              " found)".format(len(workflow.devices)))
    print(colorama.Fore.GREEN +
          "Found {0} devices!".format(len(workflow.devices)))
    if any(not x.orientation for x in workflow.devices):
        raise DeviceException("At least one of the devices has not been"
                              " properly configured, please re-run the"
                              " program with the \'configure\' option!")
    # Set up for capturing
    print("Setting up devices for capturing.")
    workflow.prepare_capture()
    # Start capture loop
    print(colorama.Fore.BLUE + "Press 'b' to capture.")
    shot_count = 0
    start_time = time.time()
    pages_per_hour = 0
    capture_keys = workflow.config['capture']['capture_keys'].as_str_seq()
    while True:
        if not getch().lower() in capture_keys:
            break
        workflow.capture()
        shot_count += len(workflow.devices)
        pages_per_hour = (3600/(time.time() - start_time))*shot_count
        status = ("\rShot {0} pages [{1:.0f}/h]"
                  .format(colorama.Fore.GREEN + unicode(shot_count),
                          pages_per_hour))
        sys.stdout.write(status)
        sys.stdout.flush()
    workflow.finish_capture()
    sys.stdout.write("\rShot {0} pages in {1:.1f} minutes, average speed was"
                     " {2:.0f} pages per hour"
                     .format(colorama.Fore.GREEN + str(shot_count),
                             (time.time() - start_time)/60, pages_per_hour))
    sys.stdout.flush()


def postprocess(workflow):
    workflow.process()


def output(workflow):
    workflow.output()


def wizard(workflow):
    # TODO: Think about how we can make this more dynamic, i.e. get list of
    #       options for plugin with a description for each entry

    print(colorama.Fore.GREEN +
          "==========================\n",
          "Starting capturing process\n",
          "==========================")
    capture(workflow)

    print(colorama.Fore.GREEN +
          "=======================\n"
          "Starting postprocessing\n"
          "=======================")
    postprocess(workflow)

    print(colorama.Fore.GREEN +
          "=================\n",
          "Generating output\n"
          "=================")
    output(workflow)


def setup_parser(config):
    def _add_argument_from_option(extname, key, option, parser):
        flag = "--{0}".format(key)
        default = (option.value
                   if not option.selectable
                   else option.value[0])
        kwargs = {'help': ("{0} [default: {1}]"
                           .format(option.docstring, default)),
                  'dest': "{0}.{1}".format(extname, key)}
        if isinstance(option.value, basestring):
            kwargs['type'] = unicode
            kwargs['metavar'] = "<str>"
        elif isinstance(option.value, bool):
            kwargs['help'] = option.docstring
            if option.value:
                flag = "--no-{0}".format(key)
                kwargs['help'] = ("Disable {0}"
                                  .format(option.docstring.lower()))
                kwargs['action'] = "store_false"
            else:
                kwargs['action'] = "store_true"
        elif isinstance(option.value, float):
            kwargs['type'] = float
            kwargs['metavar'] = "<float>"
        elif isinstance(option.value, int):
            kwargs['type'] = int
            kwargs['metavar'] = "<int>"
        elif option.selectable:
            kwargs['type'] = type(option.value[0])
            kwargs['metavar'] = "<{0}>".format("/".join(option.value))
            kwargs['choices'] = option.value
        else:
            raise TypeError("Unsupported option type")
        parser.add_argument(flag, **kwargs)

    def _add_device_arguments(name, parser):
        tmpl = get_driver(config).driver.configuration_template()
        if not tmpl:
            return
        for key, option in tmpl.iteritems():
            try:
                _add_argument_from_option('device', key, option, parser)
            except:
                return

    def _add_plugin_arguments(hooks, parser):
        extensions = get_relevant_extensions(pluginmanager, hooks)
        for ext in extensions:
            tmpl = ext.plugin.configuration_template()
            if not tmpl:
                continue
            for key, option in tmpl.iteritems():
                try:
                    _add_argument_from_option(ext.name, key, option, parser)
                except:
                    continue

    pluginmanager = get_pluginmanager(config)
    rootparser = argparse.ArgumentParser(
        description="Scanning Tool for  DIY Book Scanner")
    subparsers = rootparser.add_subparsers()

    rootparser.add_argument(
        '--verbose', '-v', dest="verbose", action="store_true")
    rootparser.add_argument(
        "path", type=unicode, help="Project path")

    wizard_parser = subparsers.add_parser(
        'wizard', help="Interactive mode")
    wizard_parser.set_defaults(subcommand='wizard')

    capture_parser = subparsers.add_parser(
        'capture', help="Start the capturing workflow")
    capture_parser.set_defaults(subcommand='capture')
    # Add arguments from plugins
    for parser in (capture_parser, wizard_parser):
        parser.add_argument(
            "--no-parallel-capture", dest="parallel_capture",
            action="store_false", default=True,
            help="Do not trigger capture on multiple devices at once.")
        _add_plugin_arguments(['prepare_capture', 'capture', 'finish_capture'],
                              parser)
        _add_device_arguments('capture', parser)

    postprocess_parser = subparsers.add_parser(
        'postprocess',
        help="Postprocess scanned images.")
    postprocess_parser.add_argument(
        "--jobs", "-j", dest="jobs", type=int, default=None,
        metavar="<int>", help="Number of concurrent processes")
    postprocess_parser.set_defaults(subcommand='postprocess')
    # Add arguments from plugins
    for parser in (postprocess_parser, wizard_parser):
        _add_plugin_arguments(['process'], parser)

    output_parser = subparsers.add_parser(
        'output',
        help="Generate output files.")
    output_parser.set_defaults(subcommand='output')
    # Add arguments from plugins
    for parser in (output_parser, wizard_parser):
        _add_plugin_arguments(['output'], parser)

    # Add custom subcommands from plugins
    pluginmanager.map(lambda x, y: x.plugin.add_command_parser(y),
                      subparsers)
    return rootparser


def main():
    # Initialize color support
    colorama.init()
    # Set to ERROR so we can see errors during plugin loading.
    logging.basicConfig(loglevel=logging.ERROR)

    # Lazy-load configuration
    config = confit.LazyConfig('spreads', __name__)
    config.read()
    setup_plugin_config(config)

    # Write default configuration to file, if it does not exist yet
    cfg_path = os.path.join(config.config_dir(), confit.CONFIG_FILENAME)
    if not os.path.exists(cfg_path):
        config.dump(filename=cfg_path)

    parser = setup_parser(config)
    args = parser.parse_args()
    # Set configuration from parsed arguments
    for argkey, value in args.__dict__.iteritems():
        if value is None or argkey == 'func':
            continue
        if '.' in argkey:
            section, key = argkey.split('.')
            config[section][key] = value
        else:
            config[argkey] = value

    loglevel = config['loglevel'].as_choice({
        'none':     logging.NOTSET,
        'info':     logging.INFO,
        'debug':    logging.DEBUG,
        'warning':  logging.WARNING,
        'error':    logging.ERROR,
        'critical': logging.CRITICAL,
    })
    if args.verbose:
        loglevel = logging.DEBUG

    # Set up logger
    logger = logging.getLogger()
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)
    handler = ColourStreamHandler()
    handler.setLevel(loglevel)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(loglevel)

    # Create workflow object
    workflow = Workflow(config)
    # Get subcommand callback by name
    subcommand = globals()[config["subcommand"].get()]
    subcommand(workflow)

    # Deinitialize color support
    colorama.deinit()
