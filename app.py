from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import os

# Flaskアプリの初期化
app = Flask(__name__)

# --- データベース設定 ---
# 環境変数からデータベースURLを取得。なければローカルのSQLiteを使う
database_uri = os.environ.get('DATABASE_URL', 'sqlite:///warikan.db')
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
# データベースの変更を追跡しない（今はFalseでOK）
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# データベースとFlaskアプリを連携
db = SQLAlchemy(app)

# --- モデル定義 ---
class PaymentStatus(db.Model):
    """イベントとメンバーの支払い状況を管理するモデル"""
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), primary_key=True)
    has_paid = db.Column(db.Boolean, default=False, nullable=False) # 支払い済みかどうか

    # Event, Memberモデルとの関連付け
    event = db.relationship('Event', back_populates='payment_statuses')
    member = db.relationship('Member', back_populates='payment_statuses')

class Member(db.Model):
    """メンバー情報を格納するテーブルの設計図"""
    id = db.Column(db.Integer, primary_key=True) # メンバー一人ひとりを識別するための番号（主キー）
    name = db.Column(db.String(100), unique=True, nullable=False) # メンバーの名前。重複不可、入力必須
    payment_statuses = db.relationship('PaymentStatus', back_populates='member', lazy='dynamic', cascade="all, delete-orphan")
    def __repr__(self):
        # デバッグ時に分かりやすく表示するためのおまじない
        return f'<Member {self.name}>'

class Event(db.Model):
    """イベント情報を格納するテーブルの設計図"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) # イベント名
    event_date = db.Column(db.Date, nullable=False) # 開催日
    total_cost = db.Column(db.Integer, default=0) # かかった費用の合計
    collected_amount = db.Column(db.Integer, default=0) # 集めた金額の合計
    surplus = db.Column(db.Integer, default=0) # 差額（繰越金/不足金）
    costs = db.relationship('CostItem', backref='event', lazy=True, cascade="all, delete-orphan")
    payment_statuses = db.relationship('PaymentStatus', back_populates='event', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Event {self.name}>'

class CostItem(db.Model):
    """個別の費用項目を格納するモデル"""
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False) # 費用の説明（例：一次会会場費）
    amount = db.Column(db.Integer, nullable=False) # 金額

    # Eventへの外部キー。どのイベントの費用かを示す
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)

    def __repr__(self):
        return f'<CostItem {self.description}>'

# --- ルーティング（URLと関数の紐付け） ---
@app.route('/')
def index():
    # 全イベントの差額（繰越金）を合計する
    total_surplus = db.session.query(db.func.sum(Event.surplus)).scalar() or 0
    # 直近のイベントを5件取得
    recent_events = Event.query.order_by(Event.event_date.desc()).limit(5).all()

    return render_template('index.html',
                           total_surplus=total_surplus,
                           recent_events=recent_events)

# メンバー表示専用のルート
@app.route('/members')
def manage_members():
    all_members = Member.query.order_by(Member.name).all()
    return render_template('members.html', members=all_members)

# メンバー追加専用のルート
@app.route('/add_member', methods=['POST'])
def add_member():
    member_name = request.form['name']
    if member_name:
        existing_member = Member.query.filter_by(name=member_name).first()
        if not existing_member:
            new_member = Member(name=member_name)
            db.session.add(new_member)
            db.session.commit()
    return redirect(url_for('manage_members'))


# メンバー削除専用のルート
@app.route('/delete_member/<int:member_id>', methods=['POST'])
def delete_member(member_id):
    # 削除対象のメンバーをIDで検索
    member_to_delete = Member.query.get_or_404(member_id)

    # データベースセッションから削除
    db.session.delete(member_to_delete)
    # 変更をコミット（保存）
    db.session.commit()

    # メンバー管理ページにリダイレクト
    return redirect(url_for('manage_members'))



# --- イベント関連のルーティング ---
# イベント一覧表示のルート
@app.route('/events')
def events_list():
    # 全てのイベントを、開催日が新しい順に取得
    all_events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('events.html', events=all_events)

# イベント追加処理のルート
@app.route('/add_event', methods=['POST'])
def add_event():
    event_name = request.form['name']
    event_date_str = request.form['event_date']

    # 日付文字列をPythonのdatetimeオブジェクトに変換
    from datetime import datetime
    event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()

    # 新しいイベントを作成してDBに保存
    new_event = Event(name=event_name, event_date=event_date)
    db.session.add(new_event)
    db.session.commit()

    return redirect(url_for('events_list'))

def update_event_surplus(event):
    """イベントの差額（繰越金）を更新するヘルパー関数"""
    event.surplus = event.collected_amount - event.total_cost
    # commitは呼び出し元で行う

def recalculate_event_cost(event):
    """イベントの合計費用を再計算して更新するヘルパー関数"""
    event.total_cost = db.session.query(db.func.sum(CostItem.amount)).filter_by(event_id=event.id).scalar() or 0
    # 差額もここで更新
    update_event_surplus(event)
    db.session.commit()

# event_detail 関数を大幅に修正

@app.route('/event/<int:event_id>', methods=['GET', 'POST'])
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    if request.method == 'POST':
        # --- 出席者更新 ---
        if 'update_attendees' in request.form:
            # 現在の出席者IDセットを取得
            current_attendee_ids = {ps.member_id for ps in event.payment_statuses}
            # フォームから送信された新しい出席者IDセットを取得
            new_attendee_ids = {int(mid) for mid in request.form.getlist('attendees')}

            # 新しく追加されたメンバーを登録
            ids_to_add = new_attendee_ids - current_attendee_ids
            for member_id in ids_to_add:
                new_status = PaymentStatus(event_id=event.id, member_id=member_id, has_paid=False)
                db.session.add(new_status)

            # 削除されたメンバーを登録解除
            ids_to_remove = current_attendee_ids - new_attendee_ids
            if ids_to_remove:
                PaymentStatus.query.filter(
                    PaymentStatus.event_id == event.id,
                    PaymentStatus.member_id.in_(ids_to_remove)
                ).delete(synchronize_session=False)

        # --- 集金額更新 ---
        elif 'update_collection_amount' in request.form:
            collected_per_person = int(request.form.get('collected_per_person', 0))
            num_attendees = event.payment_statuses.count()
            event.collected_amount = collected_per_person * num_attendees
            update_event_surplus(event)

        # --- 支払い状況更新 ---
        elif 'update_payments' in request.form:
            paid_member_ids = {int(mid) for mid in request.form.getlist('paid_members')}
            for status in event.payment_statuses:
                status.has_paid = status.member_id in paid_member_ids

        db.session.commit()
        return redirect(url_for('event_detail', event_id=event.id))

    all_members = Member.query.order_by(Member.name).all()
    # 出席済みのメンバーIDをセットで渡す
    attendee_ids = {ps.member_id for ps in event.payment_statuses}
    return render_template('event_detail.html', event=event, members=all_members, attendee_ids=attendee_ids)

@app.route('/event/<int:event_id>/add_cost', methods=['POST'])
def add_cost(event_id):
    event = Event.query.get_or_404(event_id)
    description = request.form['description']
    amount = int(request.form['amount'])

    if description and amount:
        new_cost = CostItem(description=description, amount=amount, event_id=event.id)
        db.session.add(new_cost)
        db.session.commit()
        # 合計費用を再計算
        recalculate_event_cost(event)

    return redirect(url_for('event_detail', event_id=event.id))

@app.route('/delete_cost/<int:cost_id>', methods=['POST'])
def delete_cost(cost_id):
    cost = CostItem.query.get_or_404(cost_id)
    event_id = cost.event.id
    db.session.delete(cost)
    db.session.commit()
    # 合計費用を再計算
    recalculate_event_cost(Event.query.get(event_id))

    return redirect(url_for('event_detail', event_id=event_id))

# --- アプリの実行 ---
# このファイルが直接実行された場合に、開発用サーバーを起動する
if __name__ == '__main__':
    # デバッグモードを有効にすると、コードを変更した時に自動で再起動して便利
    app.run(debug=True)