from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    HiddenField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, Regexp


class AddressForm(FlaskForm):
    email_validator = Regexp(
        r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
        message="Enter a valid email address.",
    )

    name = StringField("Name", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("Email", validators=[DataRequired(), email_validator, Length(max=120)])
    phone_number = StringField(
        "Phone",
        validators=[
            DataRequired(),
            Regexp(r"^\d{10}$", message="Phone number must be exactly 10 digits."),
        ],
    )
    address = StringField("Address", validators=[DataRequired(), Length(min=5, max=255)])
    pincode = StringField(
        "Pin Code",
        validators=[
            DataRequired(),
            Regexp(r"^\d{6}$", message="Pin Code must be exactly 6 digits."),
        ],
    )
    homeoffice = SelectField(
        "Home or Office Address",
        choices=[("home", "Home"), ("office", "Office")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Proceed to Payment")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Regexp(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", message="Enter a valid email address."),
            Length(max=120),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    submit = SubmitField("Login")


class SignupForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Regexp(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", message="Enter a valid email address."),
            Length(max=120),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    phone_number = StringField(
        "Phone Number",
        validators=[
            DataRequired(),
            Regexp(r"^\d{10}$", message="Phone number must be exactly 10 digits."),
        ],
    )
    accept_terms = BooleanField(
        "I agree to the Terms and Conditions",
        validators=[DataRequired(message="Please accept the terms to continue.")],
    )
    submit = SubmitField("Create Account")


class CheckoutForm(FlaskForm):
    payment_method = HiddenField("Payment Method", validators=[DataRequired()])
    upi_id = HiddenField("UPI ID", validators=[Optional(), Length(max=100)])
    bank_name = HiddenField("Bank Name", validators=[Optional(), Length(max=100)])
    submit = SubmitField("Confirm Payment")


class Feedbackform(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=2, max=100)])
    feedback = TextAreaField("Feedback", validators=[DataRequired(), Length(min=5, max=500)])
    submit = SubmitField("Submit")


class SupportTicketForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(min=5, max=120)])
    category = SelectField(
        "Issue Category",
        choices=[
            ("order", "Order Issue"),
            ("payment", "Payment Issue"),
            ("delivery", "Delivery Delay"),
            ("return_refund", "Return / Refund"),
            ("product_quality", "Product Quality"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )
    priority = SelectField(
        "Priority",
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        validators=[DataRequired()],
    )
    description = TextAreaField(
        "Description",
        validators=[DataRequired(), Length(min=15, max=1200)],
    )
    submit = SubmitField("Raise Ticket")


class SupportTicketMessageForm(FlaskForm):
    message = TextAreaField(
        "Message",
        validators=[DataRequired(), Length(min=2, max=1200)],
    )
    submit = SubmitField("Send Message")
