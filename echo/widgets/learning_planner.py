"""Native actionable Beta plan, using the shared server planner contract."""
from PyQt5.QtCore import Qt,pyqtSignal
from PyQt5.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFrame,QLabel,QPushButton
from echo.theme import Colors
from echo.backend.learning_path import planning_tasks


def text(value,size=12):
    w=QLabel(str(value));w.setTextFormat(Qt.PlainText);w.setWordWrap(True)
    w.setStyleSheet(f'color:{Colors.TEXT_PRIMARY};font-size:{size}px;');return w


class LearningPlanner(QWidget):
    action=pyqtSignal(str,object)
    def __init__(self,parent=None):
        super().__init__(parent);self.box=QVBoxLayout(self);self.box.setContentsMargins(0,0,0,0);self.box.setSpacing(12)
        self.tasks=[];self.buttons=[]

    def render(self,snapshot):
        while self.box.count():
            item=self.box.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        p=snapshot.get('planner') or {};self.tasks=planning_tasks(snapshot);self.buttons=[]
        self.box.addWidget(text('学习规划 · Beta',19))
        self.box.addWidget(text((snapshot.get('goal') or {}).get('target') or '先到学习目标里设定一个具体目标。',14))
        self.box.addWidget(text(p.get('summary') or '新规划服务尚未就绪，请稍后刷新。'))
        self.box.addWidget(text('任务完成由你确认，不代表已掌握。兴趣只辅助情境，不改变学习目标。'))
        self.save=QPushButton('重新保存今日规划' if p.get('stale') else '保存今日规划')
        self.save.setEnabled(bool(self.tasks));self.save.clicked.connect(lambda:self.action.emit('save_plan',{}));self.box.addWidget(self.save)
        if p.get('stale'):self.box.addWidget(text('目标或今日内容已变化，下面是新建议；请保存后再标记完成。'))
        for index,t in enumerate(self.tasks):
            card=QFrame();card.setStyleSheet(f'QFrame{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}QLabel{{border:0;background:transparent;}}')
            box=QVBoxLayout(card);box.setContentsMargins(13,12,13,12);box.setSpacing(8)
            box.addWidget(text(f"{index+1}. {t.get('title','学习任务')}",14));box.addWidget(text(t.get('reason','')))
            box.addWidget(text(str(t.get('topic',''))+' · '+str(t.get('minutes','—'))+' 分钟',11))
            row=QHBoxLayout()
            done=QPushButton('我已完成 ✓' if t.get('state')=='done' else '标记已完成')
            done.setEnabled(bool(p.get('saved')) and not p.get('stale'))
            done.clicked.connect(lambda checked=False,task=t:self.action.emit('task_state',dict(task)))
            row.addWidget(done);row.addStretch()
            title={'reflect':'开始回想','practice':'打开练习','qingjuan':'去清卷配置','studio':'课堂 Studio ↗'}[t['action']]
            start=QPushButton(title);start.clicked.connect(lambda checked=False,task=t:self.action.emit(task['action'],dict(task)))
            row.addWidget(start);self.buttons.append(start);box.addLayout(row);self.box.addWidget(card)
        self.box.addWidget(text('Studio 为独立课堂实验室，当前通过浏览器打开；不代表完整课堂已稳定。保存规划和状态不调用AI。',11));self.box.addStretch()
