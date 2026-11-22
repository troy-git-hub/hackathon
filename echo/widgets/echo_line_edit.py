"""Theme the standard editing actions instead of mixing native white menus."""
from PyQt5.QtWidgets import QLineEdit
from echo.theme import style_menu
from echo.i18n import tr


class EchoLineEdit(QLineEdit):
    def editing_menu(self):
        menu=style_menu(self.createStandardContextMenu())
        labels={'Undo':('撤销','Undo'),'Redo':('重做','Redo'),'Cut':('剪切','Cut'),
                'Copy':('复制','Copy'),'Paste':('粘贴','Paste'),'Delete':('删除','Delete'),
                'Select All':('全选','Select All')}
        for action in menu.actions():
            parts=action.text().split('\t',1);key=parts[0].replace('&','')
            if key in labels:action.setText(tr(*labels[key])+('\t'+parts[1] if len(parts)>1 else ''))
        return menu

    def contextMenuEvent(self,event):
        menu=self.editing_menu()
        try:menu.exec_(event.globalPos())
        finally:menu.deleteLater()
