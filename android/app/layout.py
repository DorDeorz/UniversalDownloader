"""The app's screens in Kivy language, built from KivyMD's Material 3 widgets.

Only the fixed structure lives here; main.py fills in texts, lists and
states. ``app.t`` looks up a text in the current language.

The look follows the FitWren step counter app: a large bold title on each
page, filled cards, a progress ring for the download, and a navigation bar
with the main page (Download) as a round button in the middle.
"""

KV = r"""
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<Section@MDLabel>:
    font_style: "Title"
    role: "small"
    theme_text_color: "Custom"
    text_color: app.theme_cls.primaryColor
    adaptive_height: True
    padding: dp(16), dp(20), dp(16), dp(4)

<Hint@MDLabel>:
    font_style: "Body"
    role: "small"
    theme_text_color: "Custom"
    text_color: app.theme_cls.onSurfaceVariantColor
    adaptive_height: True

<PageHeader@BoxLayout>:
    title: ""
    size_hint_y: None
    height: dp(64)
    padding: dp(20), 0, dp(8), 0
    spacing: dp(4)
    MDLabel:
        text: root.title
        font_style: "Headline"
        role: "small"
        bold: True
        shorten: True
        shorten_from: "right"
        pos_hint: {"center_y": .5}

# A small FitWren-style stat card: an icon, a big number and what it counts.
<StatTile@MDCard>:
    icon: ""
    style: "filled"
    orientation: "vertical"
    size_hint_y: None
    # Room for a two-line label, so both tiles of a row are the same height.
    height: max(dp(128), self.minimum_height)
    padding: dp(16)
    spacing: dp(4)
    radius: [dp(16)]
    MDIcon:
        icon: root.icon
        theme_text_color: "Custom"
        text_color: app.theme_cls.primaryColor
        adaptive_size: True

<PageAction@MDIconButton>:
    pos_hint: {"center_y": .5}

<ChoiceButton@MDButton>:
    style: "outlined"
    label: ""
    MDButtonText:
        text: root.label
    MDButtonIcon:
        icon: "menu-down"

<SearchField@MDTextField>:
    mode: "outlined"
    multiline: False
    size_hint_y: None
    MDTextFieldLeadingIcon:
        icon: "magnify"

# Error, with a button that closes it (B3-6): stays until closed or the next link.
<ErrorCard@MDCard>:
    style: "filled"
    size_hint_y: None
    height: error_box.height
    radius: [dp(16)]
    md_bg_color: app.theme_cls.errorContainerColor
    MDBoxLayout:
        id: error_box
        adaptive_height: True
        padding: dp(16), dp(12), dp(4), dp(12)
        spacing: dp(12)
        MDIcon:
            icon: "alert-circle-outline"
            pos_hint: {"center_y": .5}
            theme_text_color: "Custom"
            text_color: app.theme_cls.onErrorContainerColor
        MDLabel:
            id: error_text
            text: ""
            adaptive_height: True
            pos_hint: {"center_y": .5}
            theme_text_color: "Custom"
            text_color: app.theme_cls.onErrorContainerColor
        MDIconButton:
            id: error_close
            icon: "close"
            pos_hint: {"center_y": .5}
            theme_icon_color: "Custom"
            icon_color: app.theme_cls.onErrorContainerColor
            on_release: app.hide_error()

<LogChunk>:
    font_size: sp(12)
    size_hint_y: None
    height: self.texture_size[1]
    text_size: self.width, None
    halign: "left"
    color: app.theme_cls.onSurfaceVariantColor

<Root>:
    orientation: "vertical"
    md_bg_color: app.theme_cls.surfaceColor

    MDScreenManager:
        id: screens

        MDScreen:
            name: "home"
            MDBoxLayout:
                orientation: "vertical"

                PageHeader:
                    title: app.title
                    PageAction:
                        id: btn_paste
                        icon: "content-paste"
                        on_release: app.paste()

                MDScrollView:
                    id: home_scroll
                    do_scroll_x: False
                    MDBoxLayout:
                        id: home_box
                        orientation: "vertical"
                        adaptive_height: True
                        padding: dp(16), dp(8), dp(16), dp(24)
                        spacing: dp(14)

                        MDTextField:
                            id: url
                            mode: "outlined"
                            multiline: False
                            on_text_validate: app.analyze()
                            on_text: app.link_changed()
                            MDTextFieldLeadingIcon:
                                icon: "link-variant"
                            MDTextFieldHintText:
                                text: app.t("home.link_hint", app.lang)

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(8)
                            MDButton:
                                id: btn_clear
                                style: "text"
                                on_release: app.clear_link()
                                MDButtonIcon:
                                    icon: "close"
                                MDButtonText:
                                    text: app.t("home.clear", app.lang)
                            Widget:
                            MDButton:
                                id: btn_analyze
                                style: "filled"
                                on_release: app.analyze()
                                MDButtonIcon:
                                    id: analyze_icon
                                    icon: "magnify"
                                MDButtonText:
                                    id: analyze_text
                                    text: app.tr("link.analyze", app.lang)

                        # Links waiting their turn; tap the text for the list (move up, remove).
                        # Clear moves to a second line when a translation is long.
                        StackLayout:
                            id: queue_row
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(8)
                            MDButton:
                                id: btn_queue
                                style: "text"
                                on_release: app.show_link_queue()
                                MDButtonIcon:
                                    icon: "playlist-plus"
                                MDButtonText:
                                    id: queue_text
                                    text: ""
                            MDButton:
                                id: btn_queue_clear
                                style: "text"
                                on_release: app.clear_link_queue()
                                MDButtonText:
                                    text: app.tr("queue.clear", app.lang)

                        ErrorCard:
                            id: error_card

                        MDCard:
                            id: media_card
                            style: "filled"
                            size_hint_y: None
                            height: media_box.height
                            radius: [dp(16)]
                            MDBoxLayout:
                                id: media_box
                                adaptive_height: True
                                padding: dp(16)
                                spacing: dp(14)
                                AsyncImage:
                                    id: media_thumb
                                    size_hint: None, None
                                    size: dp(96), dp(54)
                                    pos_hint: {"center_y": .5}
                                    fit_mode: "cover"
                                    on_error: app.thumbnail_failed()
                                MDIcon:
                                    id: media_icon
                                    icon: "movie-open-outline"
                                    pos_hint: {"center_y": .5}
                                    theme_text_color: "Custom"
                                    text_color: app.theme_cls.primaryColor
                                MDBoxLayout:
                                    orientation: "vertical"
                                    adaptive_height: True
                                    spacing: dp(2)
                                    pos_hint: {"center_y": .5}
                                    MDLabel:
                                        id: media_title
                                        text: app.tr("activity.welcome", app.lang)
                                        font_style: "Title"
                                        role: "medium"
                                        adaptive_height: True
                                        shorten: False
                                    Hint:
                                        id: media_sub
                                        text: ""

                        MDButton:
                            id: btn_pick
                            style: "tonal"
                            on_release: app.choose_videos()
                            MDButtonIcon:
                                icon: "playlist-check"
                            MDButtonText:
                                id: pick_text
                                text: app.tr("playlist.title", app.lang)

                        # Why a playlist's entries were left out (B3-4).
                        MDButton:
                            id: btn_skipped
                            style: "text"
                            on_release: app.show_skipped()
                            MDButtonIcon:
                                icon: "information-outline"
                            MDButtonText:
                                id: skipped_text
                                text: ""

                        # A song opened inside a YouTube Mix: offer the whole Mix.
                        MDButton:
                            id: btn_mix
                            style: "tonal"
                            on_release: app.download_mix()
                            MDButtonIcon:
                                icon: "playlist-music"
                            MDButtonText:
                                text: app.tr("mix.download", app.lang)

                        MDLabel:
                            text: app.t("home.mode", app.lang)
                            font_style: "Label"
                            role: "large"
                            adaptive_height: True

                        StackLayout:
                            id: mode_row
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(8)
                            MDButton:
                                id: btn_video
                                style: "filled"
                                on_release: app.set_mode("video")
                                MDButtonIcon:
                                    icon: "video-outline"
                                MDButtonText:
                                    text: app.t("home.video", app.lang)
                            MDButton:
                                id: btn_audio
                                style: "outlined"
                                on_release: app.set_mode("audio")
                                MDButtonIcon:
                                    icon: "music-note-outline"
                                MDButtonText:
                                    text: app.t("home.audio", app.lang)

                        # Long translations wrap onto a second line instead of running off the screen.
                        StackLayout:
                            id: choice_row
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(8)
                            ChoiceButton:
                                id: btn_quality
                                on_release: app.choose_quality(self)
                            ChoiceButton:
                                id: btn_format
                                on_release: app.choose_format(self)

                        # Trimming and the rest stay folded until asked for (B3-2).
                        MDButton:
                            id: btn_options
                            style: "text"
                            on_release: app.toggle_options()
                            MDButtonIcon:
                                id: options_icon
                                icon: "chevron-down"
                            MDButtonText:
                                id: options_text
                                text: app.t("home.more_options", app.lang)

                        MDBoxLayout:
                            id: options_box
                            orientation: "vertical"
                            adaptive_height: True
                            spacing: dp(14)

                            MDBoxLayout:
                                adaptive_height: True
                                spacing: dp(12)
                                MDSwitch:
                                    id: trim_switch
                                    pos_hint: {"center_y": .5}
                                    on_active: app.trim_toggled(self.active)
                                MDLabel:
                                    text: app.t("home.trim", app.lang)
                                    adaptive_height: True
                                    pos_hint: {"center_y": .5}

                            MDBoxLayout:
                                id: trim_box
                                adaptive_height: True
                                spacing: dp(8)
                                padding: 0, 0, 0, dp(14)
                                MDTextField:
                                    id: trim_start
                                    mode: "outlined"
                                    multiline: False
                                    MDTextFieldHintText:
                                        text: app.tr_label("trim.start", app.lang)
                                    MDTextFieldHelperText:
                                        text: app.t("home.trim_hint", app.lang)
                                        mode: "persistent"
                                MDTextField:
                                    id: trim_end
                                    mode: "outlined"
                                    multiline: False
                                    MDTextFieldHintText:
                                        text: app.tr_label("trim.end", app.lang)
                                    MDTextFieldHelperText:
                                        text: app.t("home.trim_hint", app.lang)
                                        mode: "persistent"

                            Hint:
                                id: options_hint
                                text: app.t("home.options_hint", app.lang)

                        MDCard:
                            id: progress_card
                            style: "filled"
                            size_hint_y: None
                            height: progress_outer.height
                            radius: [dp(16)]
                            MDBoxLayout:
                                id: progress_outer
                                orientation: "vertical"
                                adaptive_height: True
                                padding: dp(16)
                                spacing: dp(8)
                                MDBoxLayout:
                                    id: progress_box
                                    adaptive_height: True
                                    spacing: dp(16)
                                    ProgressRing:
                                        id: progress
                                        size_hint: None, None
                                        size: dp(88), dp(88)
                                        pos_hint: {"center_y": .5}
                                    MDBoxLayout:
                                        orientation: "vertical"
                                        adaptive_height: True
                                        spacing: dp(6)
                                        pos_hint: {"center_y": .5}
                                        MDLabel:
                                            id: progress_title
                                            text: app.tr("progress.ready", app.lang)
                                            font_style: "Title"
                                            role: "medium"
                                            bold: True
                                            adaptive_height: True
                                        Hint:
                                            id: progress_detail
                                            text: ""
                                    MDIconButton:
                                        id: btn_pause
                                        icon: "pause"
                                        pos_hint: {"center_y": .5}
                                        opacity: 0
                                        disabled: True
                                        on_release: app.toggle_pause()
                                # After a download: open or share the file, retry, download again (B3-5, B4-5).
                                StackLayout:
                                    id: done_row
                                    size_hint_y: None
                                    height: self.minimum_height
                                    spacing: dp(8)
                                    MDButton:
                                        id: btn_open_file
                                        style: "tonal"
                                        on_release: app.open_last_file()
                                        MDButtonIcon:
                                            icon: "play-circle-outline"
                                        MDButtonText:
                                            text: app.tr("done.open_file", app.lang)
                                    MDButton:
                                        id: btn_share_file
                                        style: "outlined"
                                        on_release: app.open_last_file(share=True)
                                        MDButtonIcon:
                                            icon: "share-variant-outline"
                                        MDButtonText:
                                            text: app.t("history.share", app.lang)
                                    MDButton:
                                        id: btn_retry
                                        style: "outlined"
                                        on_release: app.retry_failed()
                                        MDButtonIcon:
                                            icon: "refresh"
                                        MDButtonText:
                                            id: retry_text
                                            text: app.tr("action.retry", app.lang)
                                    MDButton:
                                        id: btn_again
                                        style: "text"
                                        on_release: app.download_again()
                                        MDButtonIcon:
                                            icon: "download-multiple"
                                        MDButtonText:
                                            text: app.tr("history.again", app.lang)

                        MDBoxLayout:
                            id: week_row
                            adaptive_height: True
                            spacing: dp(12)
                            StatTile:
                                icon: "file-download-outline"
                                MDLabel:
                                    id: week_files
                                    text: "0"
                                    font_style: "Headline"
                                    role: "small"
                                    bold: True
                                    adaptive_height: True
                                Hint:
                                    text: app.t("home.week_files", app.lang)
                            StatTile:
                                icon: "harddisk"
                                MDLabel:
                                    id: week_size
                                    text: "0 MB"
                                    font_style: "Headline"
                                    role: "small"
                                    bold: True
                                    adaptive_height: True
                                Hint:
                                    text: app.t("home.week_size", app.lang)

                        MDButton:
                            id: btn_details
                            style: "text"
                            on_release: app.toggle_details()
                            MDButtonIcon:
                                id: details_icon
                                icon: "chevron-down"
                            MDButtonText:
                                id: details_text
                                text: app.t("home.details", app.lang)

                        # The activity log (AN-7): wrapped lines, scrolls on its own, Copy and Clear.
                        MDCard:
                            id: log_card
                            style: "outlined"
                            size_hint_y: None
                            height: log_outer.height
                            radius: [dp(12)]
                            MDBoxLayout:
                                id: log_outer
                                orientation: "vertical"
                                adaptive_height: True
                                padding: dp(12), dp(8)
                                spacing: dp(4)
                                ScrollView:
                                    id: log_scroll
                                    size_hint_y: None
                                    height: min(dp(320), log.height)
                                    do_scroll_x: False
                                    bar_width: dp(4)
                                    BoxLayout:
                                        id: log
                                        orientation: "vertical"
                                        size_hint_y: None
                                        height: self.minimum_height
                                MDBoxLayout:
                                    adaptive_height: True
                                    spacing: dp(8)
                                    Widget:
                                    MDButton:
                                        id: btn_log_copy
                                        style: "text"
                                        on_release: app.copy_log()
                                        MDButtonIcon:
                                            icon: "content-copy"
                                        MDButtonText:
                                            text: app.tr("activity.copy", app.lang)
                                    MDButton:
                                        id: btn_log_clear
                                        style: "text"
                                        on_release: app.clear_log()
                                        MDButtonIcon:
                                            icon: "delete-outline"
                                        MDButtonText:
                                            text: app.tr("activity.clear", app.lang)

                # Download / Cancel stays on screen while the page scrolls (B3-1).
                MDBoxLayout:
                    id: action_bar
                    adaptive_height: True
                    padding: dp(16), dp(8), dp(16), dp(8)
                    md_bg_color: app.theme_cls.surfaceColor
                    MDButton:
                        id: btn_download
                        style: "filled"
                        theme_width: "Custom"
                        size_hint_x: 1
                        height: dp(56)
                        on_release: app.download()
                        MDButtonIcon:
                            id: download_icon
                            icon: "download"
                        MDButtonText:
                            id: download_text
                            text: app.tr("action.download", app.lang)

        MDScreen:
            name: "history"
            MDBoxLayout:
                orientation: "vertical"
                PageHeader:
                    title: app.t("nav.history", app.lang)
                    PageAction:
                        id: btn_clear_history
                        icon: "delete-sweep-outline"
                        on_release: app.confirm_clear_history()
                MDBoxLayout:
                    id: history_search_box
                    adaptive_height: True
                    padding: dp(16), 0, dp(16), dp(4)
                    SearchField:
                        id: history_search
                        on_text: app.search_history(self.text)
                        MDTextFieldHintText:
                            text: app.tr("history.search", app.lang)
                MDScrollView:
                    do_scroll_x: False
                    MDList:
                        id: history_list
                        padding: dp(8), 0, dp(8), dp(16)

        MDScreen:
            name: "settings"
            MDBoxLayout:
                orientation: "vertical"
                PageHeader:
                    title: app.t("nav.settings", app.lang)
                MDBoxLayout:
                    id: settings_search_box
                    adaptive_height: True
                    padding: dp(16), 0, dp(16), dp(4)
                    SearchField:
                        id: settings_search
                        on_text: app.search_settings(self.text)
                        MDTextFieldHintText:
                            text: app.t("settings.search", app.lang)
                MDScrollView:
                    do_scroll_x: False
                    MDList:
                        id: settings_list
                        padding: 0, 0, 0, dp(24)

    # FitWren's navigation bar: the main page is the round button in the middle.
    BoxLayout:
        id: nav
        size_hint_y: None
        height: dp(80)
        canvas.before:
            Color:
                rgba: app.theme_cls.surfaceContainerColor
            Rectangle:
                pos: self.pos
                size: self.size
        NavTab:
            name: "history"
            icon: "history"
            text: app.t("nav.history", app.lang)
        NavTab:
            name: "home"
            icon: "download"
            text: app.t("nav.home", app.lang)
            main: True
            active: True
        NavTab:
            name: "settings"
            icon: "cog-outline"
            text: app.t("nav.settings", app.lang)

<NavTab>:
    orientation: "vertical"
    spacing: dp(4)
    padding: (0, dp(12), 0, dp(12)) if root.main else (0, dp(12), 0, dp(16))
    on_release: app.go_to(root.name)
    AnchorLayout:
        LiteIcon:
            icon: root.icon
            size: (dp(56), dp(56)) if root.main else (dp(64), dp(32))
            font_size: sp(30) if root.main else sp(24)
            color:
                (app.theme_cls.onPrimaryColor if root.active else app.theme_cls.onPrimaryContainerColor) \
                if root.main else \
                (app.theme_cls.onSecondaryContainerColor if root.active else app.theme_cls.onSurfaceVariantColor)
            canvas.before:
                Color:
                    rgba:
                        (app.theme_cls.primaryColor if root.active else app.theme_cls.primaryContainerColor) \
                        if root.main else \
                        (app.theme_cls.secondaryContainerColor[:3] + [1 if root.active else 0])
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [self.height / 2]
    Label:
        text: "" if root.main else root.text
        size_hint_y: None
        height: 0 if root.main else self.texture_size[1]
        opacity: 0 if root.main else 1
        font_size: sp(12)
        bold: root.active
        shorten: True
        text_size: self.width, None
        halign: "center"
        color: app.theme_cls.onSurfaceColor if root.active else app.theme_cls.onSurfaceVariantColor

<ProgressRing>:
    canvas:
        Color:
            rgba: app.theme_cls.outlineVariantColor
        Line:
            circle: self.center_x, self.center_y, min(self.width, self.height) / 2 - dp(5)
            width: dp(4.5)
        Color:
            rgba: app.theme_cls.primaryColor[:3] + [1 if self.value > 0 else 0]
        Line:
            circle: self.center_x, self.center_y, min(self.width, self.height) / 2 - dp(5), 0, max(self.value, 0.5) * 3.6
            width: dp(4.5)
            cap: "round"
    MDLabel:
        text: "%d%%" % root.value
        center: root.center
        size: root.size
        halign: "center"
        valign: "middle"
        font_style: "Title"
        role: "large"
        bold: True
"""
