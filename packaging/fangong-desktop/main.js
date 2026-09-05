const { app, BrowserWindow, Tray, Menu } = require('electron');
const path = require('path');

let win = null;
let tray = null;

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    title: '繁工AI',
    icon: path.join(__dirname, 'icon-512.png'),
    autoHideMenuBar: true,
  });
  win.loadURL('https://dcn2cmvd8vnq.feishuapp.com/app/app_17dfhhexbzp');
  win.on('close', (e) => { e.preventDefault(); win.hide(); });
}

app.whenReady().then(() => {
  createWindow();
  tray = new Tray(path.join(__dirname, 'icon-512.png'));
  tray.setToolTip('繁工AI');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => { win.show(); } },
    { label: '退出', click: () => { win.destroy(); app.quit(); } },
  ]));
});
