// Orbida browser extension: hands the current page or a link to the Orbida
// desktop app through the orbida: address the installer registers. The app
// starts if it is not running; the browser asks once whether to open it.

const MENU_PAGE = "orbida-page";
const MENU_LINK = "orbida-link";

function webLink(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

function sendToOrbida(tab, url) {
  const link = webLink(url);
  if (!link || !tab || tab.id === undefined) {
    return;
  }
  // An external address does not leave the page; the browser hands it to Windows.
  chrome.tabs.update(tab.id, { url: "orbida://download?url=" + encodeURIComponent(link) });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_PAGE,
      title: chrome.i18n.getMessage("menuPage"),
      contexts: ["page", "video", "audio"],
    });
    chrome.contextMenus.create({
      id: MENU_LINK,
      title: chrome.i18n.getMessage("menuLink"),
      contexts: ["link"],
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  // A video element's own address is usually a blob: the page is what Orbida can read.
  sendToOrbida(tab, info.menuItemId === MENU_LINK ? info.linkUrl : info.pageUrl);
});

chrome.action.onClicked.addListener((tab) => {
  sendToOrbida(tab, tab.url);
});
