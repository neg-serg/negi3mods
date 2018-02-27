import i3ipc
import re
import os
from modlib import Matcher
from cfg_master import CfgMaster
from singleton import Singleton


class circle(CfgMaster, Matcher):
    __metaclass__ = Singleton

    def __init__(self):
        super().__init__()
        self.tagged = {}
        self.counters = {}
        self.restore_fullscreen = []
        self.interactive = True
        self.repeats = 0
        self.winlist = []
        self.subtag_info = {}
        self.need_handle_fullscreen = True

        for tag in self.cfg:
            self.tagged[tag] = []
            self.counters[tag] = 0

        self.i3 = i3ipc.Connection()
        self.tag_windows()

        self.i3.on('window::new', self.add_wins)
        self.i3.on('window::close', self.del_wins)
        self.i3.on("window::focus", self.set_curr_win)
        self.i3.on("window::fullscreen_mode", self.handle_fullscreen)

        self.current_win = self.i3.get_tree().find_focused()

    def run_prog(self, tag, subtag=None):
        try:
            if subtag is None:
                prog_str = re.sub(
                    "~", os.path.realpath(os.path.expandvars("$HOME")),
                    self.cfg[tag]
                        .get("prog", {})
                )
            else:
                prog_str = re.sub(
                    "~", os.path.realpath(os.path.expandvars("$HOME")),
                    self.cfg[tag]
                        .get("prog_dict", {})
                        .get(subtag, {})
                        .get("prog", {})
                )
            if prog_str:
                self.i3.command('exec {}'.format(prog_str))
        except:
            pass

    def find_prioritized_win(self, tag):
        self.counters[tag] += 1
        self.repeats += 1
        if self.repeats < 8:
            self.go_next(tag)
        else:
            self.repeats = 0

    def go_next(self, tag, subtag=None):
        def twin(with_subtag=False):
            if not with_subtag:
                return self.tagged[tag][idx]
            else:
                subtag_win_classes = self.subtag_info.get("includes", {})
                for subidx, win in enumerate(self.tagged[tag]):
                    if win.window_class in subtag_win_classes:
                        return self.tagged[tag][subidx]

        def focus_next(inc_counter=True, fullscreen_handler=True, subtag=None):
            if fullscreen_handler:
                fullscreened = self.i3.get_tree().find_fullscreen()
                for win in fullscreened:
                    if self.current_win.window_class in set(self.cfg[tag]["class"]) \
                            and self.current_win.id == win.id:
                        self.need_handle_fullscreen = False
                        win.command('fullscreen disable')

            twin(subtag is not None).command('focus')

            if inc_counter:
                self.counters[tag] += 1

            if fullscreen_handler:
                now_focused = twin().id
                for id in self.restore_fullscreen:
                    if id == now_focused:
                        self.need_handle_fullscreen = False
                        self.i3.command(
                            f'[con_id={now_focused}] fullscreen enable'
                        )

            self.need_handle_fullscreen = True

        try:
            if subtag is None:
                if len(self.tagged[tag]) == 0:
                    self.run_prog(tag)
                elif len(self.tagged[tag]) <= 1:
                    idx = 0
                    focus_next(fullscreen_handler=False)
                else:
                    idx = self.counters[tag] % len(self.tagged[tag])

                    if ("priority" in self.cfg[tag]) \
                            and self.current_win.window_class \
                            not in set(self.cfg[tag]["class"]):

                        if not len([win for win in self.tagged[tag]
                                    if win.window_class ==
                                    self.cfg[tag]["priority"]]):
                            self.run_prog(tag)
                            return

                        for idx, item in enumerate(self.tagged[tag]):
                            if item.window_class == self.cfg[tag]["priority"]:
                                fullscreened = \
                                    self.i3.get_tree().find_fullscreen()
                                for win in fullscreened:
                                    tgt = self.cfg[tag]
                                    if win.window_class in tgt["class"] \
                                            and win.window_class != tgt["priority"]:
                                        self.interactive = False
                                        win.command('fullscreen disable')
                                focus_next(inc_counter=False)
                                return
                    elif self.current_win.id == twin().id:
                        self.find_prioritized_win(tag)
                    else:
                        focus_next()
            else:
                self.subtag_info = \
                    self.cfg[tag].get("prog_dict", {}).get(subtag, {})
                if not len(set(self.subtag_info.get("includes", {})) &
                           {w.window_class for w in self.tagged[tag]}):
                    self.run_prog(tag, subtag)
                else:
                    idx = 0
                    focus_next(fullscreen_handler=False, subtag=subtag)
        except KeyError:
            self.tag_windows()
            self.go_next(tag)

    def switch(self, args):
        {
            "next": self.go_next,
            "run": self.go_next,
            "reload": self.reload_config,
        }[args[0]](*args[1:])

    def find_acceptable_windows(self, tag, wlist):
        for win in wlist:
            if self.match(win, tag):
                self.tagged[tag].append(win)

    def tag_windows(self):
        self.winlist = self.i3.get_tree()
        wlist = self.winlist.leaves()
        self.tagged = {}

        for tag in self.cfg:
            self.tagged[tag] = []

        for tag in self.cfg:
            self.find_acceptable_windows(tag, wlist)

    def add_wins(self, i3, event):
        win = event.container
        for tag in self.cfg:
            if self.match(win, tag):
                try:
                    self.tagged[tag].append(win)
                except KeyError:
                    self.tag_windows()
                    self.add_wins(i3, event)
        self.winlist = self.i3.get_tree()

    def del_wins(self, i3, event):
        win = event.container
        for tag in self.cfg:
            if self.match(win, tag):
                try:
                    if self.tagged[tag] is not None:
                        for win in self.tagged[tag]:
                            if win.id in self.restore_fullscreen:
                                self.restore_fullscreen.remove(win.id)
                    del self.tagged[tag]
                except KeyError:
                    self.tag_windows()
                    self.del_wins(i3, event)
        self.winlist = self.i3.get_tree()

    def set_curr_win(self, i3, event):
        self.current_win = event.container

    def handle_fullscreen(self, i3, event):
        win = event.container
        if self.need_handle_fullscreen:
            if win.fullscreen_mode:
                if win.id not in self.restore_fullscreen:
                    self.restore_fullscreen.append(win.id)
                    return
            if not win.fullscreen_mode:
                if win.id in self.restore_fullscreen:
                    self.restore_fullscreen.remove(win.id)
                    return
