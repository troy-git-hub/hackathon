"""Native, bounded paper illustrations. No browser, scripts or external URLs."""
import ast
import base64
import math
import operator
import xml.etree.ElementTree as ET
from PyQt5.QtCore import Qt,QPointF,QRectF
from PyQt5.QtGui import QPainter,QColor,QPen,QPainterPath,QPolygonF,QImage
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget
from echo.theme import Colors


def expression(source,x):
    tree=ast.parse(str(source).replace('^','**'),mode='eval')
    if sum(1 for _ in ast.walk(tree))>70:raise ValueError()
    ops={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
    funcs={'sin':math.sin,'cos':math.cos,'tan':math.tan,'sqrt':math.sqrt,'abs':abs,'log':math.log,'exp':math.exp}
    def visit(n):
        if isinstance(n,ast.Expression):return visit(n.body)
        if isinstance(n,ast.Constant) and type(n.value) in (int,float) and abs(n.value)<1e6:return n.value
        if isinstance(n,ast.Name) and n.id in ('x','pi','e'):return {'x':x,'pi':math.pi,'e':math.e}[n.id]
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):return visit(n.operand)*(1 if isinstance(n.op,ast.UAdd) else -1)
        if isinstance(n,ast.BinOp):
            a,b=visit(n.left),visit(n.right)
            if isinstance(n.op,ast.Pow):
                if abs(b)>12 or abs(a)>1e6:raise ValueError()
                return a**b
            if type(n.op) in ops:return ops[type(n.op)](a,b)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in funcs and len(n.args)==1 and not n.keywords:return funcs[n.func.id](visit(n.args[0]))
        raise ValueError()
    result=visit(tree)
    if not isinstance(result,(int,float)) or not math.isfinite(result):raise ValueError()
    return result


def svg_bytes(source):
    if not isinstance(source,str) or len(source)>100000 or '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():return b''
    root=ET.fromstring(source)
    allowed={'svg','g','path','line','polyline','polygon','rect','circle','ellipse','text','tspan','defs','marker','title','desc','clipPath'}
    if root.tag.split('}')[-1]!='svg':return b''
    nodes=list(root.iter())
    if len(nodes)>1000:return b''
    for parent in nodes:
        for child in list(parent):
            if child.tag.split('}')[-1] not in allowed:parent.remove(child)
        for key,value in list(parent.attrib.items()):
            k=key.split('}')[-1].lower()
            if k.startswith('on') or k in ('href','style') or ('url' in value.lower() and not value.startswith('url(#')):del parent.attrib[key]
    return ET.tostring(root,encoding='utf-8')


class PaperFigure(QWidget):
    def __init__(self,figure,parent=None):
        super().__init__(parent);self.figure=figure;self.setMinimumHeight(220);self.setMaximumHeight(270)
        self.setToolTip(str(figure.get('caption','')))
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);painter.setPen(QPen(QColor(Colors.TEXT_PRIMARY),1.5))
        try:self.draw(painter)
        except Exception:
            painter.setPen(QColor(Colors.TEXT_SECONDARY));painter.drawText(self.rect(),Qt.AlignCenter,'配图格式暂不可显示，请在网页核对原图。')
    def draw(self,p):
        f=self.figure;kind=f.get('kind') or ('svg' if f.get('svg') else 'image')
        r=QRectF(22,18,self.width()-44,self.height()-36)
        if kind=='svg':
            svg=svg_bytes(f.get('svg',''));renderer=QSvgRenderer(svg)
            if not renderer.isValid():raise ValueError()
            renderer.render(p,r);return
        if kind=='image':
            source=f.get('src','')
            if not source.startswith(('data:image/png;base64,','data:image/jpeg;base64,')) or len(source)>1500000:raise ValueError()
            image=QImage.fromData(base64.b64decode(source.split(',',1)[1],validate=True))
            if image.isNull() or image.width()*image.height()>16000000:raise ValueError()
            scaled=image.scaled(int(r.width()),int(r.height()),Qt.KeepAspectRatio,Qt.SmoothTransformation)
            p.drawImage(QPointF((self.width()-scaled.width())/2,18),scaled);return
        if kind in ('bar','pie'):
            values=[float(v) for v in f.get('values',[])[:40]]
            labels=f.get('categories',f.get('labels',[]))
            if not values or min(values)<0:raise ValueError()
            if kind=='bar':
                maximum=max(1,max(values));step=r.width()/len(values)
                for ix,value in enumerate(values):
                    x=r.x()+ix*step;height=(r.height()-25)*value/maximum
                    p.fillRect(QRectF(x+4,r.bottom()-25-height,max(2,step-8),height),QColor(Colors.ACCENT))
                    p.drawText(QRectF(x,r.bottom()-23,step,23),Qt.AlignCenter,str(labels[ix]) if ix<len(labels) else str(ix+1))
            else:
                angle=0;total=sum(values)
                if total<=0:raise ValueError()
                for ix,value in enumerate(values):
                    p.setBrush(QColor.fromHsv((40+ix*45)%360,140,190));span=round(5760*value/total);p.drawPie(r,angle,span);angle+=span
            return
        if kind=='coord':box=f.get('box',[f.get('xmin',-2),f.get('ymin',-2),f.get('xmax',6),f.get('ymax',6)])
        else:box=f.get('box',[0,0,10,8])
        xmin,ymin,xmax,ymax=[float(v) for v in box]
        if not all(math.isfinite(v) and abs(v)<10000 for v in box) or xmax<=xmin or ymax<=ymin:raise ValueError()
        def point(x,y):return QPointF(r.left()+(float(x)-xmin)*r.width()/(xmax-xmin),r.bottom()-(float(y)-ymin)*r.height()/(ymax-ymin))
        if kind=='coord':
            ox=max(xmin,min(0,xmax));oy=max(ymin,min(0,ymax));p.drawLine(point(xmin,oy),point(xmax,oy));p.drawLine(point(ox,ymin),point(ox,ymax))
            p.drawText(point(xmax,oy),'x');p.drawText(point(ox,ymax),'y')
            for axis,low,high in [('x',xmin,xmax),('y',ymin,ymax)]:
                step=max(1,math.ceil((high-low)/6))
                for tick in range(math.ceil(low/step)*step,math.floor(high)+1,step):
                    pt=point(tick,oy) if axis=='x' else point(ox,tick)
                    if axis=='x':p.drawLine(pt,QPointF(pt.x(),pt.y()+4));p.drawText(QRectF(pt.x()-12,pt.y()+5,24,18),Qt.AlignCenter,str(tick))
                    else:p.drawLine(pt,QPointF(pt.x()-4,pt.y()));p.drawText(QRectF(pt.x()-30,pt.y()-9,25,18),Qt.AlignRight,str(tick))
            for fn in f.get('functions',[])[:8]:
                source=fn.get('expr','') if isinstance(fn,dict) else fn;path=QPainterPath();started=False
                for ix in range(121):
                    x=xmin+(xmax-xmin)*ix/120
                    try:y=expression(source,x)
                    except Exception:started=False;continue
                    if not ymin<=y<=ymax:started=False;continue
                    pt=point(x,y)
                    if started:path.lineTo(pt)
                    else:path.moveTo(pt);started=True
                p.setPen(QPen(QColor(Colors.ACCENT),2));p.drawPath(path)
            for item in f.get('points',[])[:20]:
                x,y=(item.get('x'),item.get('y')) if isinstance(item,dict) else item[:2]
                if not all(type(v) in (int,float) and math.isfinite(v) for v in (x,y)) or not (xmin<=x<=xmax and ymin<=y<=ymax):continue
                pt=point(x,y);p.setPen(QPen(QColor(Colors.TEXT_PRIMARY),1));p.setBrush(QColor(Colors.ACCENT));p.drawEllipse(pt,3,3)
                title=str(item.get('label','')) if isinstance(item,dict) else str(item[2]) if len(item)>2 else ''
                if title:p.drawText(QRectF(min(self.width()-85,pt.x()+5),max(0,pt.y()-20),80,20),title[:30])
            return
        if kind=='numberline':
            p.drawLine(QPointF(r.left(),r.center().y()),QPointF(r.right(),r.center().y()))
            low=float(f.get('min',-5));high=float(f.get('max',5))
            for value in range(math.ceil(low),min(math.floor(high)+1,math.ceil(low)+41)):
                x=r.left()+(value-low)/max(1,high-low)*r.width();p.drawLine(QPointF(x,r.center().y()-4),QPointF(x,r.center().y()+4));p.drawText(QRectF(x-15,r.center().y()+7,30,20),Qt.AlignCenter,str(value))
            return
        if kind=='rays':
            rays=f.get('rays',[])
            for ray in rays[:20]:
                angle=float(ray.get('angle',0))*math.pi/180;center=r.center();end=QPointF(center.x()+90*math.cos(angle),center.y()-90*math.sin(angle));p.drawLine(center,end);p.drawText(end,str(ray.get('label','')))
            return
        if kind!='geometry':raise ValueError()
        for item in f.get('elements',[])[:100]:
            typ=item.get('type');pts=item.get('points',[])
            if typ in ('polygon','polyline') and len(pts)<=100:
                polygon=QPolygonF([point(*pt) for pt in pts]);p.drawPolygon(polygon) if typ=='polygon' else p.drawPolyline(polygon)
            elif typ in ('line','segment'):
                a=item.get('from',item.get('a'));b=item.get('to',item.get('b'));p.drawLine(point(*a),point(*b))
            elif typ=='circle':
                center=point(*item.get('c',item.get('center',[0,0])));radius=float(item.get('r',1));p.drawEllipse(center,abs(radius*r.width()/(xmax-xmin)),abs(radius*r.height()/(ymax-ymin)))
            elif typ in ('point','label','text'):
                pt=point(*item.get('at',[0,0]));p.drawEllipse(pt,2,2) if typ=='point' else None;p.drawText(pt+QPointF(5,-5),str(item.get('label',item.get('text',''))))
