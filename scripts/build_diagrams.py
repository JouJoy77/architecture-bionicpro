"""Редактируемые draw.io-схемы и SVG-превью из одной раскладки."""

from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"


class Diagram:
    def __init__(self, name, title, subtitle, width=1800, height=1180):
        self.name, self.width, self.height = name, width, height
        self.file = ET.Element("mxfile", host="app.diagrams.net", version="24.8.4")
        diagram = ET.SubElement(self.file, "diagram", name=title, id=name)
        model = ET.SubElement(
            diagram,
            "mxGraphModel",
            grid="1",
            gridSize="10",
            page="1",
            pageWidth=str(width),
            pageHeight=str(height),
            pageScale="1",
        )
        self.root = ET.SubElement(model, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.nodes = {}
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8" fill="#466074"/></marker></defs>',
            f'<rect width="{width}" height="{height}" fill="white"/>',
        ]
        self.text("title", 40, 24, width - 80, 40, title, 28, "#163449")
        self.text("subtitle", 40, 70, width - 80, 32, subtitle, 17, "#506574")

    def cell(self, identifier, value, style, x, y, width, height):
        cell = ET.SubElement(
            self.root,
            "mxCell",
            id=identifier,
            value=value,
            style=style,
            vertex="1",
            parent="1",
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            x=str(x),
            y=str(y),
            width=str(width),
            height=str(height),
            **{"as": "geometry"},
        )
        return cell

    def text(self, identifier, x, y, width, height, value, size=16, color="#506574"):
        self.cell(
            identifier,
            escape(value),
            f"text;html=1;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize={size};fontColor={color};",
            x,
            y,
            width,
            height,
        )
        self.svg.append(
            f'<text x="{x}" y="{y + height / 2 + size / 3}" font-family="Arial,sans-serif" font-size="{size}" fill="{color}">{escape(value)}</text>'
        )

    def frame(self, identifier, x, y, width, height, title):
        self.cell(
            identifier,
            escape(title),
            "rounded=1;arcSize=3;html=1;whiteSpace=wrap;verticalAlign=top;align=left;spacing=20;fillColor=#f6f9fc;strokeColor=#9bafbd;dashed=1;fontSize=19;fontStyle=1;fontColor=#163449;",
            x,
            y,
            width,
            height,
        )
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="#f6f9fc" stroke="#9bafbd" stroke-dasharray="7 5"/>'
        )
        self.svg.append(
            f'<text x="{x + 20}" y="{y + 32}" font-family="Arial,sans-serif" font-size="19" font-weight="bold" fill="#163449">{escape(title)}</text>'
        )

    def node(
        self,
        identifier,
        x,
        y,
        width,
        height,
        title,
        kind,
        lines=(),
        external=False,
        person=False,
        planned=False,
    ):
        fill = "#64748b" if external or planned else "#124970" if person else "#117da2"
        label = "<b>" + escape(title) + "</b><br>[" + escape(kind) + "]"
        if lines:
            label += "<br><br>" + "<br>".join(escape(v) for v in lines)
        self.cell(
            identifier,
            label,
            f"rounded=1;arcSize=10;html=1;whiteSpace=wrap;fillColor={fill};strokeColor={fill};fontColor=#ffffff;fontSize=16;spacing=10;",
            x,
            y,
            width,
            height,
        )
        self.nodes[identifier] = (x, y, width, height)
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="{fill}"/>'
        )
        content = [
            (title, 17, True),
            (f"[{kind}]", 13, False),
            *[(v, 14, False) for v in lines],
        ]
        gap = 23
        first = y + height / 2 - (len(content) - 1) * gap / 2 + 5
        for i, (line, size, bold) in enumerate(content):
            weight = "bold" if bold else "normal"
            self.svg.append(
                f'<text x="{x + width / 2}" y="{first + i * gap}" text-anchor="middle" font-family="Arial,sans-serif" font-size="{size}" font-weight="{weight}" fill="white">{escape(line)}</text>'
            )

    def edge(self, source, target, label, points, label_at, planned=False):
        identifier = f"edge-{source}-{target}-{len(self.svg)}"
        cell = ET.SubElement(
            self.root,
            "mxCell",
            id=identifier,
            value=escape(label),
            edge="1",
            parent="1",
            source=source,
            target=target,
            style="edgeStyle=none;html=1;rounded=0;endArrow=block;strokeWidth=2;strokeColor=#466074;fontSize=14;fontColor=#29485d;labelBackgroundColor=#ffffff;",
        )
        geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if planned:
            cell.set("style", cell.get("style") + "dashed=1;")
        if len(points) > 2:
            array = ET.SubElement(geometry, "Array", **{"as": "points"})
            for x, y in points[1:-1]:
                ET.SubElement(array, "mxPoint", x=str(x), y=str(y))
        # Явные точки выхода сохраняют расположение линий в draw.io.
        sx, sy, sw, sh = self.nodes[source]
        tx, ty, tw, th = self.nodes[target]
        cell.set(
            "style",
            cell.get("style")
            + f"exitX={(points[0][0] - sx) / sw};exitY={(points[0][1] - sy) / sh};entryX={(points[-1][0] - tx) / tw};entryY={(points[-1][1] - ty) / th};",
        )
        # Label отдельным элементом: координаты одинаковы в SVG и draw.io.
        cell.set("value", "")
        x, y = label_at
        label_width = max(60, len(label) * 7.8)
        self.cell(
            identifier + "-label",
            escape(label),
            "text;html=1;align=center;verticalAlign=middle;fillColor=#ffffff;fontSize=14;fontColor=#29485d;",
            x - label_width / 2,
            y - 13,
            label_width,
            26,
        )
        joined = " ".join(f"{x},{y}" for x, y in points)
        dash = ' stroke-dasharray="7 5"' if planned else ""
        self.svg.append(
            f'<polyline points="{joined}" fill="none" stroke="#466074" stroke-width="2" marker-end="url(#arrow)"{dash}/>'
        )
        self.svg.append(
            f'<rect x="{x - label_width / 2}" y="{y - 12}" width="{label_width}" height="24" rx="3" fill="white"/>'
        )
        self.svg.append(
            f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="14" fill="#29485d">{escape(label)}</text>'
        )

    def save(self):
        ET.indent(self.file)
        ET.ElementTree(self.file).write(
            OUT / f"{self.name}.drawio", encoding="utf-8", xml_declaration=True
        )
        (OUT / f"{self.name}.svg").write_text("\n".join(self.svg + ["</svg>"]))


def auth_diagram():
    d = Diagram(
        "01-identity",
        "BionicPRO: вход и локальное хранение данных",
        "C4, целевая архитектура. Отдельное развертывание в каждой стране; общий протокол входа для приложений.",
    )
    d.node(
        "pilot",
        40,
        140,
        220,
        110,
        "Пилот протеза",
        "Person",
        ("Вход и свои отчеты",),
        person=True,
    )
    d.node(
        "ui",
        360,
        140,
        290,
        110,
        "Веб-интерфейс",
        "Container: React",
        ("Только cookie с ID сессии",),
    )
    d.text(
        "region-selection",
        800,
        145,
        930,
        36,
        "Пользователь входит по адресу своего представительства.",
        18,
    )
    d.text(
        "region-selection-note",
        800,
        190,
        930,
        36,
        "Страна учетной записи определяется по договору до входа.",
        17,
    )
    d.edge("pilot", "ui", "HTTPS", [(260, 195), (360, 195)], (310, 181))
    for prefix, x, label in [
        ("ru", 40, "Россия: данные, ключи и резервные копии в РФ"),
        ("xx", 930, "Новая страна: отдельный контур в этой стране"),
    ]:
        d.frame(prefix + "-frame", x, 330, 830, 760, label)
        a, b = x + 40, x + 450
        d.node(
            prefix + "-bff",
            a,
            420,
            300,
            130,
            "API + BFF",
            "Container: FastAPI",
            ("PKCE S256, state, nonce", "Проверка сессии и прав"),
        )
        d.node(
            prefix + "-kc",
            b,
            420,
            330,
            130,
            "Региональный Keycloak",
            "Container: OIDC broker",
            ("Единый протокол для приложений", "Федерация и внешние IdP"),
        )
        d.node(
            prefix + "-redis",
            a,
            680,
            300,
            110,
            "Серверные сессии",
            "Container: Redis",
            ("Токены зашифрованы, TTL",),
        )
        d.node(
            prefix + "-kcdb",
            b,
            680,
            330,
            110,
            "Учетные записи Keycloak",
            "Container: PostgreSQL",
            ("Локальные связи, роли, сессии",),
        )
        d.node(
            prefix + "-api",
            a,
            930,
            300,
            110,
            "Сервис отчетов",
            "Container: FastAPI",
            ("Отчеты только по iss + sub",),
        )
        d.node(
            prefix + "-idp",
            b,
            930,
            330,
            110,
            "IdP представительства",
            "Software System: внешний IdP",
            ("OIDC или SAML", "Учетные записи хранятся в стране"),
            external=True,
        )
        d.edge(
            prefix + "-bff",
            prefix + "-kc",
            "OIDC + PKCE",
            [(a + 300, 480), (b, 480)],
            (x + 395, 460),
        )
        d.edge(
            prefix + "-bff",
            prefix + "-redis",
            "ID сессии / токены",
            [(a + 150, 550), (a + 150, 680)],
            (a + 150, 615),
        )
        d.edge(
            prefix + "-kc",
            prefix + "-kcdb",
            "SQL / TLS",
            [(b + 165, 550), (b + 165, 680)],
            (b + 165, 615),
        )
        d.edge(
            prefix + "-bff",
            prefix + "-api",
            "Access token",
            [(a, 500), (x + 20, 500), (x + 20, 860), (a + 150, 860), (a + 150, 930)],
            (a + 90, 860),
        )
        d.edge(
            prefix + "-kc",
            prefix + "-idp",
            "OIDC / SAML по TLS",
            [
                (b + 330, 490),
                (x + 805, 490),
                (x + 805, 860),
                (b + 165, 860),
                (b + 165, 930),
            ],
            (b + 235, 860),
        )
    d.edge(
        "ui",
        "ru-bff",
        "HTTPS; HttpOnly session cookie",
        [(505, 250), (505, 300), (840, 300), (840, 390), (230, 390), (230, 420)],
        (670, 300),
    )
    d.edge(
        "ui",
        "xx-bff",
        "HTTPS; отдельная сессия",
        [(600, 250), (600, 270), (1730, 270), (1730, 390), (1120, 390), (1120, 420)],
        (1350, 270),
    )
    d.text(
        "note",
        40,
        1110,
        1700,
        38,
        "Стенд: один Keycloak с тестовыми пользователями. Внешние IdP и второй регион показаны как проектное решение.",
        17,
    )
    d.save()


def reports_diagram():
    d = Diagram(
        "02-reporting",
        "BionicPRO: подготовка и получение отчетов",
        "C4, один регион. Пунктир: связи целевой системы, которые заменены тестовыми данными или не входят в стенд.",
        1900,
        1320,
    )
    d.frame(
        "region",
        330,
        300,
        1530,
        920,
        "BionicPRO: региональный контур данных и вычислений",
    )
    d.frame(
        "commerce-region",
        330,
        110,
        850,
        180,
        "Магазин и CRM: размещение в том же регионе",
    )
    d.node("buyer", 40, 170, 220, 100, "Покупатель протеза", "Person", person=True)
    d.node(
        "shop",
        370,
        170,
        260,
        100,
        "Интернет-магазин",
        "Container: Битрикс24",
        planned=True,
    )
    d.node("crm", 770, 170, 260, 100, "CRM", "Container: Битрикс24", planned=True)
    d.node(
        "operator", 1300, 170, 250, 100, "Оператор производства", "Person", person=True
    )
    d.node(
        "pilot",
        40,
        400,
        220,
        110,
        "Пилот протеза",
        "Person",
        ("Настройка и свои отчеты",),
        person=True,
    )
    d.node(
        "app",
        370,
        400,
        300,
        120,
        "Клиентское приложение",
        "Container: UI",
        ("Стенд: React", "Целевая система: Android / iOS"),
    )
    d.node(
        "api",
        850,
        400,
        300,
        120,
        "API + BFF",
        "Container: FastAPI",
        ("PKCE, сессия, JWT, роль",),
    )
    d.node(
        "reports",
        1330,
        400,
        300,
        120,
        "Сервис отчетов",
        "Container: FastAPI",
        ("Проверка JWT и iss + sub", "GET /reports; JSON / CSV"),
    )
    d.node(
        "chip",
        40,
        720,
        240,
        130,
        "Программа в протезе",
        "Software System: C++",
        ("Распознавание на устройстве", "Отправка по 4G"),
        external=True,
    )
    d.node(
        "telemetry",
        370,
        720,
        300,
        130,
        "DB телеметрии",
        "Container: PostgreSQL",
        ("Входные события", "Отдельно от CRM"),
    )
    d.node(
        "crmdb",
        850,
        720,
        300,
        130,
        "CRM DB (стенд)",
        "Container: PostgreSQL",
        ("Клиенты, iss + sub", "История владения протезом"),
    )
    d.node(
        "ch",
        1330,
        720,
        440,
        150,
        "OLAP: готовая витрина",
        "Container: ClickHouse",
        (
            "Пользователь + протез + сутки UTC",
            "Партиция: день; сортировка: iss + sub",
            "Данные и готовность публикуются вместе",
        ),
    )
    d.node(
        "airflow",
        740,
        1030,
        420,
        130,
        "Планировщик ETL",
        "Container: Apache Airflow",
        ("Ежедневно 00:00 UTC, catchup", "Extract -> join -> aggregate -> publish"),
    )
    d.node(
        "cli",
        1420,
        990,
        300,
        90,
        "CLI для ML",
        "Container: Python",
        ("Отдельные права на датасеты",),
        planned=True,
    )
    d.node("ml", 1420, 1130, 300, 70, "ML-инженер", "Person", person=True)
    d.edge(
        "ml",
        "cli",
        "Запрос данных",
        [(1570, 1130), (1570, 1080)],
        (1570, 1105),
        planned=True,
    )
    d.edge(
        "buyer",
        "shop",
        "Заказ / оплата",
        [(260, 220), (370, 220)],
        (315, 202),
        planned=True,
    )
    d.edge(
        "shop",
        "crm",
        "Заказ, HTTPS",
        [(630, 220), (770, 220)],
        (700, 202),
        planned=True,
    )
    d.edge(
        "operator",
        "crm",
        "Учет производства",
        [(1300, 220), (1030, 220)],
        (1165, 202),
        planned=True,
    )
    d.edge(
        "crm",
        "crmdb",
        "Запись в CRM DB",
        [(900, 270), (900, 280), (1210, 280), (1210, 685), (1000, 685), (1000, 720)],
        (1222, 635),
        planned=True,
    )
    d.edge("pilot", "app", "HTTPS", [(260, 455), (370, 455)], (315, 437))
    d.edge(
        "pilot", "chip", "Миосигналы", [(80, 510), (80, 720)], (80, 665), planned=True
    )
    d.edge(
        "app",
        "chip",
        "Настройка протеза (моб.)",
        [(430, 520), (430, 560), (240, 560), (240, 720)],
        (370, 560),
        planned=True,
    )
    d.edge("app", "api", "Сессия; GET /reports", [(670, 455), (850, 455)], (760, 437))
    d.edge("api", "reports", "Access JWT", [(1150, 455), (1330, 455)], (1240, 437))
    d.edge(
        "reports",
        "ch",
        "SELECT: iss + sub, период",
        [(1550, 520), (1550, 720)],
        (1550, 620),
    )
    d.edge(
        "chip",
        "api",
        "Телеметрия: HTTPS / 4G",
        [(160, 720), (160, 600), (900, 600), (900, 520)],
        (600, 600),
        planned=True,
    )
    d.edge(
        "api",
        "telemetry",
        "Прием и запись событий",
        [(1000, 520), (1000, 650), (520, 650), (520, 720)],
        (750, 650),
        planned=True,
    )
    d.edge(
        "airflow",
        "telemetry",
        "SELECT, read-only",
        [(810, 1030), (810, 940), (520, 940), (520, 850)],
        (620, 940),
    )
    d.edge(
        "airflow",
        "crmdb",
        "SELECT, read-only",
        [(1000, 1030), (1000, 850)],
        (1000, 940),
    )
    d.edge(
        "airflow",
        "ch",
        "Готовая суточная партиция",
        [(1160, 1095), (1250, 1095), (1250, 810), (1330, 810)],
        (1340, 950),
    )
    d.edge(
        "cli",
        "ch",
        "SELECT, отдельная роль",
        [(1570, 990), (1570, 870)],
        (1570, 930),
        planned=True,
    )
    d.text(
        "scope",
        40,
        1240,
        1820,
        40,
        "Вход и сессии см. на схеме 01. В стенде seed заполняет CRM DB и DB телеметрии; API приема телеметрии и ML CLI не реализованы.",
        17,
    )
    d.save()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    auth_diagram()
    reports_diagram()
    combined = ET.parse(OUT / "00-original.drawio.xml").getroot()
    combined.find("diagram").set("name", "Исходная архитектура")
    for name in ("01-identity", "02-reporting"):
        combined.append(ET.parse(OUT / f"{name}.drawio").getroot().find("diagram"))
    ET.indent(combined)
    ET.ElementTree(combined).write(
        OUT / "BionicPRO_C4_model.drawio.xml", encoding="utf-8", xml_declaration=True
    )
