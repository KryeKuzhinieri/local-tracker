from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from gi.repository import Gtk

ProjectKey = tuple[str, str]
DailyTotals = dict[date, dict[ProjectKey, int]]
Bucket = tuple[str, dict[ProjectKey, int]]


def color_components(value: str) -> tuple[float, float, float]:
    color = value.removeprefix("#")
    if len(color) != 6:
        return 0.49, 0.44, 0.94
    return (
        int(color[0:2], 16) / 255,
        int(color[2:4], 16) / 255,
        int(color[4:6], 16) / 255,
    )


class TimeBarChart(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__(hexpand=True, height_request=260)
        self._buckets: list[Bucket] = []
        self.set_draw_func(self._draw)

    def set_data(self, start: date, end: date, daily_totals: DailyTotals) -> None:
        self._buckets = self._aggregate(start, end, daily_totals)
        self.queue_draw()

    def _aggregate(
        self, start: date, end: date, daily_totals: DailyTotals
    ) -> list[Bucket]:
        day_count = (end - start).days + 1
        if day_count <= 45:
            return [
                (
                    day.strftime("%d %b"),
                    daily_totals.get(day, {}),
                )
                for day in self._days(start, end)
            ]

        grouped: dict[date, dict[ProjectKey, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        monthly = day_count > 180
        for day in self._days(start, end):
            key = day.replace(day=1) if monthly else day - timedelta(days=day.weekday())
            for project, seconds in daily_totals.get(day, {}).items():
                grouped[key][project] += seconds

        return [
            (
                key.strftime("%b %y") if monthly else f"W{key.isocalendar().week}",
                dict(values),
            )
            for key, values in sorted(grouped.items())
        ]

    @staticmethod
    def _days(start: date, end: date):
        day = start
        while day <= end:
            yield day
            day += timedelta(days=1)

    def _draw(self, _area, context, width: int, height: int) -> None:
        left, right, top, bottom = 52, 12, 16, 34
        plot_width = max(1, width - left - right)
        plot_height = max(1, height - top - bottom)
        totals = [sum(projects.values()) for _, projects in self._buckets]

        context.select_font_face("Sans")
        if not totals or max(totals, default=0) == 0:
            context.set_source_rgba(0.60, 0.62, 0.68, 1)
            context.set_font_size(14)
            context.move_to(max(left, width / 2 - 75), height / 2)
            context.show_text("No time in this range")
            return

        maximum_hours = max(1, math.ceil(max(totals) / 3600))
        maximum_seconds = maximum_hours * 3600
        context.set_font_size(11)
        for index in range(5):
            fraction = index / 4
            y = top + plot_height * (1 - fraction)
            context.set_source_rgba(1, 1, 1, 0.09)
            context.set_line_width(1)
            context.move_to(left, y)
            context.line_to(width - right, y)
            context.stroke()
            context.set_source_rgba(0.60, 0.62, 0.68, 1)
            context.move_to(6, y + 4)
            context.show_text(f"{maximum_hours * fraction:g}h")

        slot_width = plot_width / len(self._buckets)
        bar_width = max(2, min(24, slot_width * 0.68))
        for bucket_index, (label, projects) in enumerate(self._buckets):
            x = left + bucket_index * slot_width + (slot_width - bar_width) / 2
            y = top + plot_height
            for (_name, color), seconds in sorted(
                projects.items(), key=lambda item: item[0][0].casefold()
            ):
                segment_height = plot_height * seconds / maximum_seconds
                y -= segment_height
                red, green, blue = color_components(color)
                context.set_source_rgb(red, green, blue)
                context.rectangle(x, y, bar_width, max(1, segment_height))
                context.fill()

            label_stride = max(1, math.ceil(len(self._buckets) / 8))
            if (
                bucket_index % label_stride == 0
                or bucket_index == len(self._buckets) - 1
            ):
                context.set_source_rgba(0.60, 0.62, 0.68, 1)
                context.set_font_size(10)
                context.move_to(max(left, x - 8), height - 10)
                context.show_text(label)
