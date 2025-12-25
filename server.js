if (process.env.NODE_ENV !== "production") {
  require("dotenv").config();
}
const express = require("express");
const cors = require("cors");
const Stripe = require("stripe");
const admin = require("firebase-admin");

const app = express();
app.use(cors());

// Stripe needs raw body for webhooks
app.use("/webhook", express.raw({ type: "application/json" }));
app.use(express.json());

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);

admin.initializeApp({
  credential: admin.credential.cert({
    projectId: process.env.FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY.replace(/\\n/g, "\n"),
  }),
});


const db = admin.firestore();

const PRICE_IDS = {
  starter: null,
  pro_monthly: "price_1Si3I56k3VtieV2BgIuYByYy",
  pro_yearly: "price_1Si3IL6k3VtieV2BTn7iZUe9",
};

app.post("/create-checkout-session", async (req, res) => {
  const { uid, tier, interval } = req.body;

  if (!uid || !tier || !interval) {
    return res.status(400).send("Missing params");
  }

  const key = `${tier}_${interval}`;
  const priceId = PRICE_IDS[key];
  if (!priceId) return res.status(400).send("Invalid plan");

  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      payment_method_types: ["card"],
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: "https://veritas-chi-ten.vercel.app/chat",
      cancel_url: "https://veritas-chi-ten.vercel.app/membership",
      metadata: { uid, tier, interval },
    });

    res.json({ url: session.url });
  } catch (e) {
    console.error(e);
    res.status(500).send("Stripe error");
  }
});

app.post("/create-portal-session", async (req, res) => {
  const { uid, returnUrl } = req.body;
  if (!uid) return res.status(400).send("Missing uid");

  const snap = await db.collection("users").doc(uid).get();
  const customerId = snap.data()?.billing?.customerId;
  if (!customerId) return res.status(400).send("No customer");

  const portal = await stripe.billingPortal.sessions.create({
    customer: customerId,
    return_url: returnUrl,
  });

  res.json({ url: portal.url });
});

app.post("/webhook", (req, res) => {
  const sig = req.headers["stripe-signature"];
  let event;

  try {
    event = stripe.webhooks.constructEvent(
      req.body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET
    );
  } catch (err) {
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  handleStripeEvent(event).then(() => {
    res.json({ received: true });
  });
});

async function handleStripeEvent(event) {
  const obj = event.data.object;

  if (
    event.type === "checkout.session.completed" ||
    event.type === "customer.subscription.updated" ||
    event.type === "customer.subscription.created"
  ) {
    const uid = obj.metadata?.uid || obj.metadata?.uid;
    if (!uid) return;

    const customerId = obj.customer;
    const sub = obj.subscription || obj.id;
    const status = obj.status || "active";
    const periodEnd = obj.current_period_end
      ? admin.firestore.Timestamp.fromMillis(obj.current_period_end * 1000)
      : null;

    await db.collection("users").doc(uid).set(
      {
        billing: {
          customerId,
          subscriptionId: sub,
          status,
          currentPeriodEnd: periodEnd,
          updatedAt: admin.firestore.FieldValue.serverTimestamp(),
        },
      },
      { merge: true }
    );
  }
}

const PORT = process.env.PORT || 4242;
app.listen(PORT, () => {
  console.log("Stripe server running on port", PORT);
});


