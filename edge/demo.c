#include <stdio.h>
#include "lunar_models.h"

int main(void) {
    /* Sample candidate site feature vector (8 input features) */
    const float candidate_site[LUNAR_N_FEATURES] = {
        -85.31f,  /* Latitude (deg) */
         3.20f,   /* Terrain slope (deg) */
         0.82f,   /* Solar illumination fraction */
         0.91f,   /* Earth Direct-to-Earth (DTE) visibility */
        25.00f,   /* Solar mast height (m) */
         1.40f,   /* Surface roughness index */
        12.50f,   /* Distance to nearest PSR (km) */
       145.00f    /* Local elevation reference (m) */
    };

    float score = lunar_score(candidate_site);

    float class_proba[3] = {0.0f};
    lunar_class_proba(candidate_site, class_proba);

    float mean = 0.0f, sd = 0.0f;
    lunar_uncertainty(candidate_site, &mean, &sd);

    printf("=== Lunar South Pole Edge AI Inference ===\n");
    printf("Suitability Score : %.2f / 100\n", score);
    printf("Ensemble Estimate : %.2f +/- %.2f (1-sigma)\n", mean, sd);
    printf("Class Probabilities: [Class 0: %.3f | Class 1: %.3f | Class 2: %.3f]\n",
           class_proba[0], class_proba[1], class_proba[2]);

    return 0;
}