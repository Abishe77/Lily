document.querySelector(".start-gate").addEventListener("click", startIntro, { once: true });

function startIntro() {
    gsap.to(".start-gate", { opacity: 0, duration: 0.4, onComplete: () => {
        document.querySelector(".start-gate").style.display = "none";
    }});

    document.fonts.ready.then(() => {
        prepareAndRun();
    });
}

function splitIntoLetters(el) {
    const text = el.textContent;
    el.textContent = "";
    text.split("").forEach(char => {
        const span = document.createElement("span");
        span.className = "letter";
        span.textContent = char === " " ? "\u00A0" : char;
        el.appendChild(span);
    });
}

function prepareAndRun() {
    const textEl = document.querySelector(".companion-text");

    splitIntoLetters(textEl);

    const textWidth = textEl.getBoundingClientRect().width;
    const flowerWidth = 160;
    const gap = 40;

    const totalWidth = flowerWidth + gap + textWidth;
    const groupLeft = (window.innerWidth - totalWidth) / 2;

    const flowerTargetLeft = groupLeft + (flowerWidth / 2);
    const textTargetLeft = groupLeft + flowerWidth + gap;

    textEl.style.left = textTargetLeft + "px";
    textEl.style.visibility = "visible";

    runTimeline(flowerTargetLeft);
}

function runTimeline(flowerTargetLeft) {

    const dropSound = document.getElementById("dropSound");
    const bloomSound = document.getElementById("bloomSound");

    gsap.set(".droplet", { scaleY: 0.3, scaleX: 0.3, opacity: 0, transformOrigin: "50% 0%" });
    gsap.set(".ripple", { scale: 0, opacity: 0 });
    gsap.set(".flower", { scale: 0, opacity: 0, xPercent: -50, yPercent: -50 });
    gsap.set(".petal-outer, .petal-inner", { scale: 0 });
    gsap.set(".companion-text", { yPercent: -50 });
    gsap.set(".letter", { opacity: 0, y: 10, scale: 0.5 });

    const tl = gsap.timeline();

    tl.to(".droplet", { opacity: 1, scaleY: 0.6, scaleX: 0.6, duration: 0.6, ease: "power1.out" });
    tl.to(".droplet", { scaleY: 1.4, scaleX: 0.7, duration: 0.5, ease: "power2.out" });
    tl.to(".droplet", {
        y: () => window.innerHeight * 0.63,
        scaleY: 1.6,
        scaleX: 0.75,
        duration: 1.3,
        ease: "power2.in"
    }, "-=0.1");

    tl.to(".droplet", {
        scaleX: 3.2,
        scaleY: 0.25,
        duration: 0.35,
        ease: "power1.out",
        onStart: () => dropSound.play()
    });

    tl.to(".droplet", { opacity: 0, duration: 0.4, ease: "power1.out" }, "-=0.1");

    tl.to(".ripple-1", { scale: 13, opacity: 0.6, duration: 2.0, ease: "power2.out" }, "-=0.75");
    tl.to(".ripple-2", { scale: 9,  opacity: 0.4, duration: 1.7, ease: "power2.out" }, "-=1.9");
    tl.to(".ripple-3", { scale: 6,  opacity: 0.3, duration: 1.4, ease: "power2.out" }, "-=1.6");
    tl.to(".ripple-1, .ripple-2, .ripple-3", { opacity: 0, duration: 0.6 }, "-=0.5");

    tl.to(".flower", { opacity: 1, scale: 0.3, duration: 0.5, ease: "power1.out" }, "-=1.0");
    tl.to(".flower", { scale: 1, duration: 1.4, ease: "back.out(1.4)" }, "+=0.1");
    tl.to(".petal-outer", { scale: 1, duration: 1.2, stagger: 0.12, ease: "back.out(2)" }, "<");
    tl.to(".petal-inner", {
        scale: 1,
        duration: 1.0,
        stagger: 0.1,
        ease: "back.out(2)",
        onStart: () => bloomSound.play()
    }, "-=0.6");

    tl.to(".flower-group", { scale: 1.12, duration: 0.3, ease: "power1.out", yoyo: true, repeat: 1 });

    // RISE — flower slides up to vertical center
    tl.to(".flower", {
        top: "50%",
        duration: 1.1,
        ease: "power2.inOut"
    }, "+=0.3");

    // SHIFT RIGHT (to calculated centered-group position) + LETTERS POP IN
    tl.to(".flower", {
        left: flowerTargetLeft + "px",
        duration: 1.8,
        ease: "power2.inOut"
    }, "+=0.1");

    tl.to(".letter", {
        opacity: 1,
        y: 0,
        scale: 1,
        duration: 0.25,
        stagger: 0.07,
        ease: "back.out(2)"
    }, "<");

    // HOLD a beat so it's actually readable
    tl.to({}, { duration: 1.2 });

    // EXIT — both fade and drift downward together
    tl.to(".flower, .letter", {
        opacity: 0,
        y: "+=50",
        duration: 0.9,
        ease: "power1.in"
    });
}