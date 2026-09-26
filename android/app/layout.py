"""The app's screens in Kivy language, built from KivyMD's Material 3 widgets.

Only the fixed structure lives here; main.py fills in texts, lists and
states. ``app.t`` looks up a text in the current language.
"""

KV = r"""
#:import dp kivy.metrics.dp

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

<ChoiceButton@MDButton>:
    style: "outlined"
    label: ""
    MDButtonText:
        text: root.label
    MDButtonIcon:
        icon: "menu-down"

<Root>:
    orientation: "vertical"
    md_bg_color: app.theme_cls.surfaceColor

    MDScreenManager:
        id: screens

        MDScreen:
            name: "home"
            MDBoxLayout:
                orientation: "vertical"

                MDTopAppBar:
                    type: "small"
                    MDTopAppBarTitle:
                        text: "UniversalDownloader"
                    MDTopAppBarTrailingButtonContainer:
                        MDActionTopAppBarButton:
                            icon: "content-paste"
                            on_release: app.paste()

                MDScrollView:
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
                                    icon: "magnify"
                                MDButtonText:
                                    text: app.tr("link.analyze", app.lang)

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

                        MDLabel:
                            text: app.t("home.mode", app.lang)
                            font_style: "Label"
                            role: "large"
                            adaptive_height: True

                        MDBoxLayout:
                            adaptive_height: True
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

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(8)
                            ChoiceButton:
                                id: btn_quality
                                on_release: app.choose_quality(self)
                            ChoiceButton:
                                id: btn_format
                                on_release: app.choose_format(self)

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
                                    text: app.tr("trim.start", app.lang).split()[0]
                                MDTextFieldHelperText:
                                    text: app.t("home.trim_hint", app.lang)
                                    mode: "persistent"
                            MDTextField:
                                id: trim_end
                                mode: "outlined"
                                multiline: False
                                MDTextFieldHintText:
                                    text: app.tr("trim.end", app.lang).split()[0]
                                MDTextFieldHelperText:
                                    text: app.t("home.trim_hint", app.lang)
                                    mode: "persistent"

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

                        MDCard:
                            id: progress_card
                            style: "outlined"
                            size_hint_y: None
                            height: progress_box.height
                            radius: [dp(16)]
                            MDBoxLayout:
                                id: progress_box
                                orientation: "vertical"
                                adaptive_height: True
                                padding: dp(16)
                                spacing: dp(10)
                                MDLabel:
                                    id: progress_title
                                    text: app.tr("progress.ready", app.lang)
                                    adaptive_height: True
                                MDLinearProgressIndicator:
                                    id: progress
                                    size_hint_y: None
                                    height: dp(6)
                                    value: 0
                                Hint:
                                    id: progress_detail
                                    text: ""

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

                        MDLabel:
                            id: log
                            text: ""
                            font_style: "Body"
                            role: "small"
                            adaptive_height: True
                            theme_text_color: "Custom"
                            text_color: app.theme_cls.onSurfaceVariantColor

        MDScreen:
            name: "history"
            MDBoxLayout:
                orientation: "vertical"
                MDTopAppBar:
                    type: "small"
                    MDTopAppBarTitle:
                        text: app.t("nav.history", app.lang)
                    MDTopAppBarTrailingButtonContainer:
                        MDActionTopAppBarButton:
                            icon: "delete-sweep-outline"
                            on_release: app.confirm_clear_history()
                MDScrollView:
                    do_scroll_x: False
                    MDList:
                        id: history_list
                        padding: dp(8), 0, dp(8), dp(16)

        MDScreen:
            name: "settings"
            MDBoxLayout:
                orientation: "vertical"
                MDTopAppBar:
                    type: "small"
                    MDTopAppBarTitle:
                        text: app.t("nav.settings", app.lang)
                MDScrollView:
                    do_scroll_x: False
                    MDList:
                        id: settings_list
                        padding: 0, 0, 0, dp(24)

    MDNavigationBar:
        id: nav
        on_switch_tabs: app.switch_tab(args[1].name)

        NavItem:
            name: "home"
            icon: "download-circle-outline"
            text: app.t("nav.home", app.lang)
            active: True
        NavItem:
            name: "history"
            icon: "history"
            text: app.t("nav.history", app.lang)
        NavItem:
            name: "settings"
            icon: "cog-outline"
            text: app.t("nav.settings", app.lang)

<NavItem>:
    MDNavigationItemIcon:
        icon: root.icon
    MDNavigationItemLabel:
        text: root.text
"""
